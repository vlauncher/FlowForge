"""Concurrent budget exhaustion tests (P9-T06)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.errors import BudgetExceededError
from app.core.ids import new_id
from app.modules.executions.models import WorkflowRun
from app.modules.identity.models import User
from app.modules.organizations.models import Membership, Organization
from app.modules.usage.budget import (
    get_org_committed_and_reserved_budget,
    reserve_budget,
)
from app.modules.workflows.models import Workflow, WorkflowVersion


@pytest.mark.asyncio
async def test_p9_t06_budget_concurrency_race(
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """P9-T06: Concurrent budget reservation prevents over-allocation.

    Given an org with budget limit 10,000 µUSD,
    When 10 concurrent requests each attempt to reserve 3,000 µUSD,
    Then at most 3 succeed (9,000 <= 10,000), and the remaining fail with BUDGET_EXCEEDED.
    Total committed + reserved never exceeds 10,000 µUSD.
    """
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    settings = get_settings()
    settings.llm_price_per_1k_tokens_micro_usd = 1000  # so max_tokens=500 -> 3000 µUSD

    org_id = new_id()
    user_id = new_id()
    wf_id = new_id()
    ver_id = new_id()

    user = User(
        id=user_id,
        email="budget_tester@example.com",
        password_hash="hash",
        display_name="Budget Tester",
    )
    org = Organization(
        id=org_id,
        name="Budget Test Org",
        slug=f"budget-org-{org_id.hex[:6]}",
        budget_limit_micro_usd=10000,
        max_concurrent_runs=20,
    )
    membership = Membership(org_id=org_id, user_id=user_id, role="owner")
    workflow = Workflow(
        id=wf_id,
        org_id=org_id,
        display_name="Budget Test Workflow",
        created_by=user_id,
    )
    version = WorkflowVersion(
        id=ver_id,
        workflow_id=wf_id,
        org_id=org_id,
        version=1,
        status="published",
        definition_json={"start": "ai", "steps": [{"id": "ai", "type": "llm_classify"}]},
        schema_version=1,
        checksum="checksum",
        published_at=datetime.now(UTC),
    )

    db_session.add_all([user, org, membership, workflow, version])

    # Pre-create 10 runs
    run_ids: list[UUID] = []
    for _ in range(10):
        rid = new_id()
        run_ids.append(rid)
        run = WorkflowRun(
            id=rid,
            org_id=org_id,
            workflow_id=wf_id,
            version_id=ver_id,
            state="RUNNING",
            trigger_kind="manual",
            inputs={},
            context={},
            attempt_epoch=0,
        )
        db_session.add(run)

    await db_session.commit()

    # Launch 10 concurrent reservations
    success_count = 0
    failure_count = 0

    async def attempt_reservation(r_id: UUID) -> bool:
        async with session_factory() as session:
            async with session.begin():
                try:
                    await reserve_budget(
                        session,
                        org_id=org_id,
                        run_id=r_id,
                        step_id="ai_step",
                        max_tokens=500,  # ((500 + 1000) * 1000) // 1000 * 2 = 3000
                    )
                    return True
                except BudgetExceededError:
                    return False

    results = await asyncio.gather(*[attempt_reservation(rid) for rid in run_ids])

    success_count = sum(1 for r in results if r is True)
    failure_count = sum(1 for r in results if r is False)

    # At most 3 can succeed because 3 * 3,000 = 9,000 <= 10,000, and 4th would be 12,000 > 10,000
    assert success_count == 3
    assert failure_count == 7

    async with session_factory() as session:
        total = await get_org_committed_and_reserved_budget(session, org_id=org_id)
        assert total == 9000
        assert total <= 10000
