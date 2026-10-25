"""API router for audit events."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.domain.permissions import Action
from app.infrastructure.db.session import get_session
from app.modules.audit.schemas import AuditEventsPageResponse
from app.modules.audit.service import AuditService
from app.modules.organizations.models import Membership

router = APIRouter(tags=["Audit"])


@router.get(
    "/organizations/{org_id}/audit-events",
    response_model=AuditEventsPageResponse,
    status_code=status.HTTP_200_OK,
    summary="List organization audit events",
)
async def list_audit_events(
    org_id: UUID,
    membership: Annotated[Membership, Depends(require_permission(Action.AUDIT_READ))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
) -> AuditEventsPageResponse:
    """Retrieve a paginated audit trail for the organization.

    Requires AUDIT_READ permission (owner or admin).
    """
    service = AuditService(session)
    return await service.list_events(
        org_id=org_id,
        action=action,
        limit=limit,
        cursor=cursor,
    )
