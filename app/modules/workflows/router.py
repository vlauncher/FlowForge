"""HTTP endpoints for workflow authoring, versioning, and validation."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_membership, require_permission
from app.core.errors import ForbiddenError, NotFoundError
from app.core.pagination import Page
from app.domain.permissions import Action, has_permission
from app.infrastructure.db.session import get_session
from app.modules.identity.models import User
from app.modules.organizations.models import Membership
from app.modules.workflows.models import Workflow
from app.modules.workflows.schemas import (
    WorkflowCreateRequest,
    WorkflowPublishRequest,
    WorkflowResponse,
    WorkflowValidateRequest,
    WorkflowValidateResponse,
    WorkflowVersionCreateRequest,
    WorkflowVersionResponse,
    WorkflowVersionSummaryResponse,
    WorkflowVersionUpdateRequest,
)
from app.modules.workflows.service import WorkflowService

router = APIRouter(tags=["Workflows"])


async def get_workflow_and_membership(
    workflow_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> tuple[Workflow, str]:
    """Retrieve workflow joined with caller's membership or raise 404."""
    service = WorkflowService(session)
    result = await service.repo.get_by_id_for_user(workflow_id, user_id=current_user.id)
    if not result:
        raise NotFoundError("Workflow not found")
    return result


def require_workflow_permission(
    action: Action | str,
) -> Callable[..., Coroutine[Any, Any, tuple[Workflow, str]]]:
    """Dependency checking that caller holds action permission within the organization."""

    async def _dependency(
        workflow_and_role: Annotated[tuple[Workflow, str], Depends(get_workflow_and_membership)],
    ) -> tuple[Workflow, str]:
        wf, role = workflow_and_role
        if not has_permission(role, action):
            raise ForbiddenError(f"Role '{role}' lacks permission '{action}'")
        return wf, role

    return _dependency


# ---------------------------------------------------------------------------
# Workflow Shell Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/organizations/{org_id}/workflows",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workflow",
)
async def create_workflow(
    org_id: UUID,
    payload: WorkflowCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    membership: Annotated[Membership, Depends(require_permission(Action.WORKFLOW_WRITE))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowResponse:
    service = WorkflowService(session)
    return await service.create_workflow(
        org_id=org_id,
        req=payload,
        user_id=current_user.id,
    )


@router.get(
    "/organizations/{org_id}/workflows",
    response_model=Page[WorkflowResponse],
    status_code=status.HTTP_200_OK,
    summary="List workflows in an organization",
)
async def list_workflows(
    org_id: UUID,
    membership: Annotated[Membership, Depends(get_membership)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> Page[WorkflowResponse]:
    service = WorkflowService(session)
    return await service.list_workflows(
        org_id=org_id,
        include_archived=include_archived,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Get workflow by ID (asserting caller membership)",
)
async def get_workflow(
    workflow_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowResponse:
    service = WorkflowService(session)
    return await service.get_workflow_for_user(workflow_id, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Workflow Version Endpoints (Phase 3)
# ---------------------------------------------------------------------------


@router.post(
    "/workflows/{workflow_id}/versions",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new draft version for a workflow",
)
async def create_workflow_version(
    workflow_id: UUID,
    payload: WorkflowVersionCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    wf_and_role: Annotated[
        tuple[Workflow, str], Depends(require_workflow_permission(Action.WORKFLOW_WRITE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionResponse:
    wf, _ = wf_and_role
    service = WorkflowService(session)
    return await service.create_version_draft(
        org_id=wf.org_id,
        workflow_id=wf.id,
        user_id=current_user.id,
        req=payload,
    )


@router.put(
    "/workflows/{workflow_id}/versions/{version_num}",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing draft version definition",
)
async def update_workflow_version(
    workflow_id: UUID,
    version_num: int,
    payload: WorkflowVersionUpdateRequest,
    wf_and_role: Annotated[
        tuple[Workflow, str], Depends(require_workflow_permission(Action.WORKFLOW_WRITE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionResponse:
    wf, _ = wf_and_role
    service = WorkflowService(session)
    return await service.update_version_draft(
        org_id=wf.org_id,
        workflow_id=wf.id,
        version_num=version_num,
        req=payload,
    )


@router.get(
    "/workflows/{workflow_id}/versions",
    response_model=Page[WorkflowVersionSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List versions of a workflow",
)
async def list_workflow_versions(
    workflow_id: UUID,
    wf_and_role: Annotated[
        tuple[Workflow, str], Depends(require_workflow_permission(Action.WORKFLOW_READ))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[WorkflowVersionSummaryResponse]:
    wf, _ = wf_and_role
    service = WorkflowService(session)
    return await service.list_versions(
        org_id=wf.org_id,
        workflow_id=wf.id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/workflows/{workflow_id}/versions/{version_num}",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get workflow version details",
)
async def get_workflow_version(
    workflow_id: UUID,
    version_num: int,
    wf_and_role: Annotated[
        tuple[Workflow, str], Depends(require_workflow_permission(Action.WORKFLOW_READ))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowVersionResponse:
    wf, _ = wf_and_role
    service = WorkflowService(session)
    return await service.get_version(
        org_id=wf.org_id,
        workflow_id=wf.id,
        version_num=version_num,
    )


@router.post(
    "/workflows/{workflow_id}/validate",
    response_model=WorkflowValidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate workflow definition graph and schema",
)
async def validate_workflow(
    workflow_id: UUID,
    payload: WorkflowValidateRequest,
    wf_and_role: Annotated[
        tuple[Workflow, str], Depends(require_workflow_permission(Action.WORKFLOW_READ))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowValidateResponse:
    wf, _ = wf_and_role
    service = WorkflowService(session)
    return await service.validate_workflow(
        org_id=wf.org_id,
        workflow_id=wf.id,
        req=payload,
    )


@router.post(
    "/workflows/{workflow_id}/publish",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish a workflow version",
)
async def publish_workflow(
    workflow_id: UUID,
    wf_and_role: Annotated[
        tuple[Workflow, str], Depends(require_workflow_permission(Action.WORKFLOW_PUBLISH))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: WorkflowPublishRequest = WorkflowPublishRequest(),
) -> WorkflowVersionResponse:
    wf, _ = wf_and_role
    service = WorkflowService(session)
    return await service.publish_workflow(
        org_id=wf.org_id,
        workflow_id=wf.id,
        req=payload,
    )
