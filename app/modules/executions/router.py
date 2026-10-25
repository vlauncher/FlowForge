"""HTTP endpoints for triggering and inspecting workflow runs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.infrastructure.db.session import get_session
from app.modules.executions.schemas import (
    RunActionRequest,
    RunDetail,
    RunResponse,
    RunsPageResponse,
    StepAttemptsListResponse,
    TriggerRunRequest,
)
from app.modules.executions.service import ExecutionService
from app.modules.identity.models import User

router = APIRouter(tags=["Executions"])


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a workflow run",
)
async def trigger_run(
    workflow_id: UUID,
    req: TriggerRunRequest,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunResponse:
    """Enqueues a new execution run for the specified workflow."""
    service = ExecutionService(session)
    run_response, is_replayed = await service.trigger_run(
        workflow_id=workflow_id,
        req=req,
        user_id=current_user.id,
        idempotency_key=idempotency_key,
    )

    response.headers["Location"] = run_response.status_url
    if is_replayed:
        response.headers["Idempotency-Replayed"] = "true"

    return run_response


@router.get(
    "/runs/{run_id}",
    response_model=RunDetail,
    summary="Get workflow run details",
)
async def get_run(
    run_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunDetail:
    """Retrieve execution state, step progress, inputs, and outputs of a workflow run."""
    service = ExecutionService(session)
    return await service.get_run_detail(run_id, user_id=current_user.id)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunDetail,
    status_code=status.HTTP_200_OK,
    summary="Cancel a workflow run",
)
async def cancel_run(
    run_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: RunActionRequest = RunActionRequest(),
) -> RunDetail:
    """Cancels a queued/waiting run immediately, or flags a running execution for cancellation."""
    service = ExecutionService(session)
    return await service.cancel_run(run_id, user_id=current_user.id)


@router.post(
    "/runs/{run_id}/retry",
    response_model=RunDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed workflow run",
)
async def retry_run(
    run_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: RunActionRequest = RunActionRequest(),
) -> RunDetail:
    """Retries a failed workflow run from the failed step."""
    service = ExecutionService(session)
    return await service.retry_run(run_id, user_id=current_user.id)


@router.get(
    "/runs/{run_id}/steps",
    response_model=StepAttemptsListResponse,
    summary="Get execution step attempts",
)
async def get_run_step_attempts(
    run_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StepAttemptsListResponse:
    """Retrieve all chronological step execution attempts for a run."""
    service = ExecutionService(session)
    return await service.list_step_attempts(run_id, user_id=current_user.id)


@router.get(
    "/organizations/{org_id}/runs",
    response_model=RunsPageResponse,
    summary="List runs in an organization",
)
async def list_runs_by_org(
    org_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    workflow_id: Annotated[UUID | None, Query()] = None,
) -> RunsPageResponse:
    """List execution runs for an organization with keyset cursor pagination."""
    service = ExecutionService(session)
    return await service.list_runs_by_org(
        org_id=org_id,
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
        state=state,
        workflow_id=workflow_id,
    )
