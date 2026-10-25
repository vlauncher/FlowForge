"""Repository for managing usage_records."""

from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.models import WorkflowRun
from app.modules.organizations.models import Organization
from app.modules.usage.models import UsageRecord
from app.modules.usage.schemas import ModelUsageItem, UsageTotals


class UsageRepository:
    """Data access repository for LLM usage tracking."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_usage(
        self,
        *,
        org_id: UUID,
        run_id: UUID,
        step_id: str,
        attempt_id: UUID | None,
        provider: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        estimated_cost_micro_usd: int,
        billed_cost_micro_usd: int,
        latency_ms: int,
        prompt_template_id: str,
        prompt_template_version: int,
        outcome: str,
    ) -> UsageRecord:
        """Create and persist an immutable usage record."""
        record = UsageRecord(
            id=uuid4(),
            org_id=org_id,
            run_id=run_id,
            step_id=step_id,
            attempt_id=attempt_id,
            provider=provider,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_micro_usd=estimated_cost_micro_usd,
            billed_cost_micro_usd=billed_cost_micro_usd,
            latency_ms=latency_ms,
            prompt_template_id=prompt_template_id,
            prompt_template_version=prompt_template_version,
            outcome=outcome,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def count_today_calls(
        self,
        *,
        org_id: UUID,
        provider: str = "openrouter",
    ) -> int:
        """Count today's provider calls for the specified organization."""
        today_start = datetime.datetime.now(datetime.UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        stmt = (
            sa.select(sa.func.count(UsageRecord.id))
            .where(UsageRecord.org_id == org_id)
            .where(UsageRecord.provider == provider)
            .where(UsageRecord.created_at >= today_start)
        )
        result = await self.session.scalar(stmt)
        return int(result or 0)

    async def get_usage_summary(
        self,
        *,
        org_id: UUID,
        from_dt: datetime.datetime,
        to_dt: datetime.datetime,
    ) -> dict[str, Any]:
        """Aggregate usage totals, model breakdown, budget limit, and run state counts."""
        # 1. Budget limit from Organization
        org_res = await self.session.execute(
            sa.select(Organization.budget_limit_micro_usd).where(Organization.id == org_id)
        )
        budget_limit = int(org_res.scalar_one_or_none() or 0)

        # 2. Aggregated totals from UsageRecord
        totals_stmt = sa.select(
            sa.func.count(UsageRecord.id).label("llm_calls"),
            sa.func.coalesce(sa.func.sum(UsageRecord.prompt_tokens), 0).label("prompt_tokens"),
            sa.func.coalesce(sa.func.sum(UsageRecord.completion_tokens), 0).label(
                "completion_tokens"
            ),
            sa.func.coalesce(sa.func.sum(UsageRecord.total_tokens), 0).label("total_tokens"),
            sa.func.coalesce(sa.func.sum(UsageRecord.estimated_cost_micro_usd), 0).label(
                "estimated_cost_micro_usd"
            ),
            sa.func.coalesce(sa.func.sum(UsageRecord.billed_cost_micro_usd), 0).label(
                "billed_cost_micro_usd"
            ),
        ).where(
            UsageRecord.org_id == org_id,
            UsageRecord.created_at >= from_dt,
            UsageRecord.created_at <= to_dt,
        )
        t_row = (await self.session.execute(totals_stmt)).one()
        totals = UsageTotals(
            llm_calls=int(t_row.llm_calls or 0),
            prompt_tokens=int(t_row.prompt_tokens or 0),
            completion_tokens=int(t_row.completion_tokens or 0),
            total_tokens=int(t_row.total_tokens or 0),
            estimated_cost_micro_usd=int(t_row.estimated_cost_micro_usd or 0),
            billed_cost_micro_usd=int(t_row.billed_cost_micro_usd or 0),
        )

        # 3. Model breakdown
        model_stmt = (
            sa.select(
                UsageRecord.provider,
                UsageRecord.model_name,
                sa.func.count(UsageRecord.id).label("calls"),
                sa.func.coalesce(sa.func.sum(UsageRecord.total_tokens), 0).label("total_tokens"),
                sa.func.coalesce(sa.func.sum(UsageRecord.estimated_cost_micro_usd), 0).label(
                    "estimated_cost_micro_usd"
                ),
                sa.func.coalesce(sa.func.sum(UsageRecord.billed_cost_micro_usd), 0).label(
                    "billed_cost_micro_usd"
                ),
            )
            .where(
                UsageRecord.org_id == org_id,
                UsageRecord.created_at >= from_dt,
                UsageRecord.created_at <= to_dt,
            )
            .group_by(UsageRecord.provider, UsageRecord.model_name)
        )
        m_rows = (await self.session.execute(model_stmt)).all()
        by_model = [
            ModelUsageItem(
                provider=str(row.provider),
                model_name=str(row.model_name),
                calls=int(row.calls or 0),
                total_tokens=int(row.total_tokens or 0),
                estimated_cost_micro_usd=int(row.estimated_cost_micro_usd or 0),
                billed_cost_micro_usd=int(row.billed_cost_micro_usd or 0),
            )
            for row in m_rows
        ]

        # 4. Run counts by state
        runs_stmt = (
            sa.select(WorkflowRun.state, sa.func.count(WorkflowRun.id))
            .where(
                WorkflowRun.org_id == org_id,
                WorkflowRun.created_at >= from_dt,
                WorkflowRun.created_at <= to_dt,
            )
            .group_by(WorkflowRun.state)
        )
        r_rows = (await self.session.execute(runs_stmt)).all()
        runs_by_state = {
            "QUEUED": 0,
            "RUNNING": 0,
            "WAITING_APPROVAL": 0,
            "SUCCEEDED": 0,
            "FAILED": 0,
            "CANCELLED": 0,
        }
        for st, count in r_rows:
            if st in runs_by_state:
                runs_by_state[st] = int(count)

        return {
            "budget_limit_micro_usd": budget_limit,
            "totals": totals,
            "by_model": by_model,
            "runs_by_state": runs_by_state,
        }
