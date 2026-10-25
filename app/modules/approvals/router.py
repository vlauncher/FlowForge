"""API router for human approval gate endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_permission
from app.domain.permissions import Action
from app.infrastructure.db.session import get_session
from app.modules.approvals.schemas import (
    ApprovalDecisionRequest,
    ApprovalOut,
    ApprovalsPageResponse,
)
from app.modules.approvals.service import ApprovalService
from app.modules.identity.models import User
from app.modules.organizations.models import Membership

router = APIRouter(tags=["Approvals"])


@router.get(
    "/organizations/{org_id}/approvals",
    response_model=ApprovalsPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List organization approval requests",
)
async def list_approvals(
    org_id: UUID,
    membership: Annotated[Membership, Depends(require_permission(Action.APPROVAL_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> ApprovalsPageResponse:
    """List approval requests for an organization with optional state filter."""
    service = ApprovalService(session)
    return await service.list_approvals(
        org_id=org_id,
        state=state,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/approvals/{approval_id}",
    response_model=ApprovalOut,
    status_code=status.HTTP_200_OK,
    summary="Get approval request details",
)
async def get_approval(
    approval_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApprovalOut:
    """Retrieve details of an approval request asserting caller membership."""
    service = ApprovalService(session)
    return await service.get_approval(approval_id, user_id=current_user.id)


@router.post(
    "/approvals/{approval_id}/decisions",
    response_model=ApprovalOut,
    status_code=status.HTTP_200_OK,
    summary="Decide a pending approval request",
)
async def decide_approval(
    approval_id: UUID,
    req: ApprovalDecisionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApprovalOut:
    """Approve or reject a pending approval request enforcing role hierarchy and race safety."""
    service = ApprovalService(session)
    return await service.decide_approval(
        approval_id,
        user_id=current_user.id,
        req=req,
    )
