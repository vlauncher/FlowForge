"""API router for organization usage and cost reporting."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.domain.permissions import Action
from app.infrastructure.db.session import get_session
from app.modules.organizations.models import Membership
from app.modules.usage.schemas import OrgUsageResponse
from app.modules.usage.service import UsageService

router = APIRouter(tags=["Usage"])


@router.get(
    "/organizations/{org_id}/usage",
    response_model=OrgUsageResponse,
    status_code=status.HTTP_200_OK,
    summary="Get organization usage and cost analytics",
    description="Retrieve aggregated token counts, model breakdown, and run counts.",
)
async def get_org_usage(
    org_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    membership: Annotated[Membership, Depends(require_permission(Action.USAGE_READ))],
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
) -> OrgUsageResponse:
    """Retrieve usage analytics within the specified time window."""
    service = UsageService(session)
    return await service.get_org_usage(
        org_id=org_id,
        from_dt=from_time,
        to_dt=to_time,
    )
