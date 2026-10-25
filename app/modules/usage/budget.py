"""Two-phase budget reservation and settlement for AI workflow executions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import BudgetExceededError, NotFoundError
from app.core.ids import new_id
from app.modules.organizations.models import Organization
from app.modules.usage.models import BudgetReservation, UsageRecord

logger = logging.getLogger("flowforge.budget")


def compute_max_step_cost(max_tokens: int) -> int:
    """Compute maximum step cost in micro-USD for 2 attempts."""
    settings = get_settings()
    # ((step.config.max_tokens + 1000) * settings.llm_price_per_1k_tokens_micro_usd) // 1000 * 2
    return ((max_tokens + 1000) * settings.llm_price_per_1k_tokens_micro_usd) // 1000 * 2


async def get_org_committed_and_reserved_budget(
    session: AsyncSession,
    *,
    org_id: UUID,
) -> int:
    """Calculate the sum of all SETTLED spend and active RESERVED budget for an org."""
    settled_stmt = select(func.coalesce(func.sum(BudgetReservation.settled_micro_usd), 0)).where(
        BudgetReservation.org_id == org_id,
        BudgetReservation.state == "SETTLED",
    )
    settled_sum = (await session.scalar(settled_stmt)) or 0

    reserved_stmt = select(func.coalesce(func.sum(BudgetReservation.reserved_micro_usd), 0)).where(
        BudgetReservation.org_id == org_id,
        BudgetReservation.state == "RESERVED",
    )
    reserved_sum = (await session.scalar(reserved_stmt)) or 0

    return int(settled_sum + reserved_sum)


async def check_organization_budget(
    session: AsyncSession,
    *,
    org_id: UUID,
) -> None:
    """Verify that an organization has not already exceeded its budget limit.

    Must be called inside an active transaction, holding or acquiring the
    exclusive row lock on organizations for org_id.
    """
    stmt = (
        select(Organization.budget_limit_micro_usd)
        .where(Organization.id == org_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    budget_limit = result.scalar_one_or_none()
    if budget_limit is None:
        raise NotFoundError(f"Organization '{org_id}' not found")

    total_committed = await get_org_committed_and_reserved_budget(session, org_id=org_id)
    if total_committed >= budget_limit:
        raise BudgetExceededError(
            f"Org budget limit ({budget_limit} µUSD) reached (committed: {total_committed} µUSD)"
        )


async def reserve_budget(
    session: AsyncSession,
    *,
    org_id: UUID,
    run_id: UUID,
    step_id: str,
    max_tokens: int,
) -> int:
    """Reserve estimated cost before an LLM step execution.

    Locks the organizations row FOR UPDATE to prevent concurrency races.
    Returns the reserved_micro_usd.
    """
    max_step_cost = compute_max_step_cost(max_tokens)

    # 1. Lock org row FOR UPDATE
    stmt = (
        select(Organization.budget_limit_micro_usd)
        .where(Organization.id == org_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    budget_limit = result.scalar_one_or_none()
    if budget_limit is None:
        raise NotFoundError(f"Organization '{org_id}' not found")

    # 2. Check total committed + reserved + max_step_cost against budget limit
    total_committed = await get_org_committed_and_reserved_budget(session, org_id=org_id)
    if total_committed + max_step_cost > budget_limit:
        raise BudgetExceededError(
            f"Budget limit exceeded: {total_committed} + {max_step_cost} > {budget_limit} µUSD"
        )

    # 3. Upsert budget_reservations row
    existing_stmt = select(BudgetReservation).where(
        BudgetReservation.org_id == org_id,
        BudgetReservation.run_id == run_id,
        BudgetReservation.step_id == step_id,
    )
    existing_res = (await session.execute(existing_stmt)).scalar_one_or_none()

    if existing_res:
        existing_res.reserved_micro_usd = max_step_cost
        existing_res.state = "RESERVED"
        existing_res.settled_micro_usd = None
        existing_res.settled_at = None
    else:
        reservation = BudgetReservation(
            id=new_id(),
            org_id=org_id,
            run_id=run_id,
            step_id=step_id,
            reserved_micro_usd=max_step_cost,
            state="RESERVED",
        )
        session.add(reservation)

    await session.flush()
    return max_step_cost


async def settle_budget(
    session: AsyncSession,
    *,
    org_id: UUID,
    run_id: UUID,
    step_id: str,
) -> int:
    """Settle actual cost for a step from usage_records and transition reservation to SETTLED."""
    actual_stmt = select(func.coalesce(func.sum(UsageRecord.estimated_cost_micro_usd), 0)).where(
        UsageRecord.org_id == org_id,
        UsageRecord.run_id == run_id,
        UsageRecord.step_id == step_id,
    )
    actual_cost = int((await session.scalar(actual_stmt)) or 0)

    stmt = (
        update(BudgetReservation)
        .where(
            BudgetReservation.org_id == org_id,
            BudgetReservation.run_id == run_id,
            BudgetReservation.step_id == step_id,
        )
        .values(
            settled_micro_usd=actual_cost,
            state="SETTLED",
            settled_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.execute(stmt)
    await session.flush()
    return actual_cost


async def release_budget(
    session: AsyncSession,
    *,
    org_id: UUID,
    run_id: UUID,
    step_id: str,
) -> None:
    """Release an active reservation if no LLM calls were made or on cancel/skip."""
    stmt = (
        update(BudgetReservation)
        .where(
            BudgetReservation.org_id == org_id,
            BudgetReservation.run_id == run_id,
            BudgetReservation.step_id == step_id,
            BudgetReservation.state == "RESERVED",
        )
        .values(
            settled_micro_usd=0,
            state="RELEASED",
            settled_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.execute(stmt)
    await session.flush()
