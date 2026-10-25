"""Integration tests for duplicate message delivery and stale worker fencing (P4-T10, P4-T11)."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.executions.models import StepAttempt, WorkflowRun
from app.workers.runner import execute_run


async def get_auth_token(client: AsyncClient, email: str) -> str:
    signup_res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return signup_res.json()["access_token"]


def simple_workflow() -> dict:
    return {
        "schema_version": 1,
        "name": "Simple Flow",
        "inputs_schema": {"type": "object"},
        "start": "step_1",
        "steps": [
            {
                "id": "step_1",
                "type": "set_data",
                "config": {"values": {"foo": "bar"}},
                "next": "step_2",
            },
            {
                "id": "step_2",
                "type": "set_data",
                "config": {"values": {"baz": "qux"}},
                "next": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_duplicate_delivery_idempotency(client: AsyncClient, db_engine: AsyncEngine) -> None:
    """P4-T10: Calling execute_run(run_id) multiple times produces exactly 1 attempt per step."""
    token = await get_auth_token(client, "dedup@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post("/v1/organizations", json={"name": "Dedup Org"}, headers=headers)
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Dedup Flow"},
        headers=headers,
    )
    wf_id = wf_res.json()["id"]

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": simple_workflow()},
        headers=headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)

    run_res = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = run_res.json()["run_id"]

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # Deliver 5 times concurrently
    tasks = [asyncio.create_task(execute_run(run_id, session_factory=factory)) for _ in range(5)]
    await asyncio.gather(*tasks)

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.state == "SUCCEEDED"

        # Exactly 2 steps in definition -> exactly 2 step_attempts
        att_stmt = select(StepAttempt).where(StepAttempt.run_id == run_id)
        att_res = await session.execute(att_stmt)
        attempts = list(att_res.scalars().all())
        assert len(attempts) == 2


@pytest.mark.asyncio
async def test_stale_worker_fencing(client: AsyncClient, db_engine: AsyncEngine) -> None:
    """P4-T11: Worker A epoch=1 lease expires; Worker B reclaims epoch=2; Worker A cannot write."""
    token = await get_auth_token(client, "fencing@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post("/v1/organizations", json={"name": "Fence Org"}, headers=headers)
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Fence Flow"},
        headers=headers,
    )
    wf_id = wf_res.json()["id"]

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": simple_workflow()},
        headers=headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)

    run_res = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = run_res.json()["run_id"]

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # 1. Simulate Worker A claiming the run with epoch=1
    async with factory() as session:
        async with session.begin():
            claim_sql = text("""
                UPDATE workflow_runs
                SET state = 'RUNNING',
                    lease_owner = 'worker-A',
                    lease_expires_at = now() - interval '10 seconds',
                    heartbeat_at = now() - interval '10 seconds',
                    attempt_epoch = 1,
                    started_at = now()
                WHERE id = :run_id
            """)
            await session.execute(claim_sql, {"run_id": run_id})

    # 2. Worker B executes the run (reclaiming because lease_expires_at < now())
    await execute_run(run_id, session_factory=factory, worker_id="worker-B")

    async with factory() as session:
        run_b = await session.get(WorkflowRun, run_id)
        assert run_b is not None
        assert run_b.state == "SUCCEEDED"
        # Epoch was incremented from 1 to 2
        assert run_b.attempt_epoch == 2

    # 3. Simulate Worker A waking up and trying to commit a step result with stale epoch=1
    async with factory() as session:
        async with session.begin():
            fence_stmt = select(WorkflowRun).where(
                WorkflowRun.id == run_id,
                WorkflowRun.state == "RUNNING",
                WorkflowRun.attempt_epoch == 1,
            )
            res = await session.execute(fence_stmt)
            stale_row = res.scalar_one_or_none()
            # Stale worker A is fenced!
            assert stale_row is None
