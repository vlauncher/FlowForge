"""API endpoints for managing triggers and ingesting signed webhook events."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.infrastructure.db.session import get_session
from app.modules.executions.schemas import RunResponse
from app.modules.identity.models import User
from app.modules.triggers.schemas import CreateTriggerRequest, TriggerOut
from app.modules.triggers.service import TriggerService

router = APIRouter(tags=["Triggers"])


@router.post(
    "/workflows/{workflow_id}/triggers",
    response_model=TriggerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a webhook trigger for a workflow",
)
async def create_trigger(
    workflow_id: UUID,
    req: CreateTriggerRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TriggerOut:
    """Register a new HMAC-signed webhook trigger endpoint for a workflow."""
    service = TriggerService(session)
    return await service.create_trigger(workflow_id, req, user_id=current_user.id)


@router.get(
    "/workflows/{workflow_id}/triggers",
    response_model=list[TriggerOut],
    status_code=status.HTTP_200_OK,
    summary="List triggers for a workflow",
)
async def list_triggers(
    workflow_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TriggerOut]:
    """Retrieve all triggers configured for a specific workflow."""
    service = TriggerService(session)
    return await service.list_triggers(workflow_id, user_id=current_user.id)


@router.post(
    "/triggers/webhooks/{trigger_id}",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger workflow execution via signed webhook",
)
async def ingest_webhook(
    trigger_id: UUID,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunResponse:
    """Public ingest endpoint verifying HMAC-SHA256 signature and triggering workflow."""
    raw_body = await request.body()
    service = TriggerService(session)
    run_response, is_replayed = await service.process_webhook(
        trigger_id=trigger_id,
        raw_body=raw_body,
        headers=request.headers,
    )

    response.headers["Location"] = run_response.status_url
    if is_replayed:
        response.headers["Idempotency-Replayed"] = "true"

    return run_response
