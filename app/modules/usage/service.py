"""Service layer for usage reporting and cost aggregation (Phase 8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.usage.repository import UsageRepository
from app.modules.usage.schemas import OrgUsageResponse


class UsageService:
    """Business logic for usage and cost reporting."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UsageRepository(session)

    async def get_org_usage(
        self,
        *,
        org_id: UUID,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> OrgUsageResponse:
        """Return aggregated token metrics, costs, and run state distribution."""
        effective_to = to_dt or datetime.now(UTC)
        effective_from = from_dt or (effective_to - timedelta(days=30))

        summary = await self.repo.get_usage_summary(
            org_id=org_id,
            from_dt=effective_from,
            to_dt=effective_to,
        )

        return OrgUsageResponse(
            org_id=org_id,
            from_time=effective_from,
            to_time=effective_to,
            budget_limit_micro_usd=summary["budget_limit_micro_usd"],
            totals=summary["totals"],
            by_model=summary["by_model"],
            runs_by_state=summary["runs_by_state"],
        )
