"""Integration test for sweeper crash recovery and lease reclamation (P5-T11)."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.executions.models import OutboxEvent, WorkflowRun
from app.modules.integrations.models import ToolEffect
from app.workers.runner import execute_run
from app.workers.sweeper import sweep_stale_and_delayed_runs


async def create_user_and_token(client: AsyncClient, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["user"]["id"], data["access_token"]


@pytest.mark.asyncio
async def test_sweeper_recovers_crashed_worker_skipping_committed_steps(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T11: Stale lease with step 1 COMMITTED recovered by sweeper; worker 2 reclaims, skips step 1, executes step 2."""
    _, token = await create_user_and_token(client, "p5t11_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T11 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "stripe_api",
            "provider": "stripe",
            "secret": "sk_test_p5t11",
            "allowed_hosts": ["api.stripe.com"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    # 2-step workflow: step_1 (HTTP) -> step_2 (HTTP)
    definition = {
        "schema_version": 1,
        "name": "Two-Step Crash Recovery Flow",
        "inputs_schema": {"type": "object", "required": [], "properties": {}},
        "start": "step_1",
        "steps": [
            {
                "id": "step_1",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://api.stripe.com/v1/customers",
                    "credential_id": cred_id,
                    "effect": "write",
                },
                "next": "step_2",
            },
            {
                "id": "step_2",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://api.stripe.com/v1/charges",
                    "credential_id": cred_id,
                    "effect": "write",
                },
                "next": None,
            },
        ],
    }

    wf_resp = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Two Step Flow"},
        headers=headers,
    )
    wf_id = wf_resp.json()["id"]

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)

    run_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = UUID(run_resp.json()["run_id"])

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Simulate Worker 1 crashing after step_1 committed its effect:
    # Set state='RUNNING', lease_expires_at = now() - 10s, attempt_epoch=1, current_step_id='step_1'
    async with session_factory() as session:
        async with session.begin():
            # ToolEffect for step_1 already COMMITTED
            eff1 = ToolEffect(
                org_id=UUID(org_id),
                run_id=run_id,
                step_id="step_1",
                provider="stripe",
                idempotency_key=f"{run_id}:step_1",
                state="COMMITTED",
                request_hash="hash_1",
                external_ref="cus_recovered_111",
                response_summary={
                    "status": 200,
                    "body": {"id": "cus_recovered_111"},
                    "headers": {},
                },
            )
            session.add(eff1)

            # Stale lease on workflow_runs
            await session.execute(
                text("""
                    UPDATE workflow_runs
                    SET state = 'RUNNING',
                        lease_owner = 'worker-crashed-1',
                        lease_expires_at = now() - interval '10 seconds',
                        attempt_epoch = 1,
                        current_step_id = 'step_1',
                        started_at = now() - interval '30 seconds',
                        updated_at = now() - interval '10 seconds'
                    WHERE id = :id
                """),
                {"id": run_id},
            )

    # 1. Run sweeper: should identify stale lease and insert RunResumeRequested
    recovered_count = await sweep_stale_and_delayed_runs(session_factory)
    assert recovered_count == 1

    # Verify OutboxEvent was inserted
    async with session_factory() as session:
        evt_res = await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == run_id,
                OutboxEvent.event_type == "RunResumeRequested",
            )
        )
        evt = evt_res.scalar_one_or_none()
        assert evt is not None
        assert evt.payload["reason"] == "sweeper_recovery_running"

    # 2. Worker 2 reclaims and executes the run
    called_endpoints: list[str] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        called_endpoints.append(str(request.url))
        if "charges" in str(request.url):
            return httpx.Response(200, json={"id": "ch_recovered_222"})
        return httpx.Response(200, json={"id": "unexpected"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)

    # 3. Assert external calls:
    # step_1 (/customers) was NOT called over the wire (skipped because COMMITTED in ledger)
    # step_2 (/charges) was called exactly once
    assert len(called_endpoints) == 1
    assert "https://api.stripe.com/v1/charges" in called_endpoints[0]

    # 4. Verify run finished SUCCEEDED with attempt_epoch bumped
    async with session_factory() as session:
        r_res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        final_run = r_res.scalar_one()
        assert final_run.state == "SUCCEEDED"
        assert final_run.attempt_epoch == 2  # Incremented on reclaim
        assert final_run.context["step_1"]["body"]["id"] == "cus_recovered_111"
        assert final_run.context["step_2"]["body"]["id"] == "ch_recovered_222"
