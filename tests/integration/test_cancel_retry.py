"""Integration tests for run cancellation and manual retries (P5-T12 and P5-T13)."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.executions.models import OutboxEvent, StepAttempt
from app.workers.runner import execute_run


async def create_user_and_token(client: AsyncClient, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["user"]["id"], data["access_token"]


async def setup_two_step_workflow(
    client: AsyncClient,
    headers: dict[str, str],
    org_id: str,
) -> tuple[str, str]:
    """Create and publish a 2-step workflow: step_1 (set_data) -> step_2 (set_data)."""
    wf_resp = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Two Step Cancel Retry Flow"},
        headers=headers,
    )
    wf_id = wf_resp.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Two Step Cancel Retry Flow",
        "inputs_schema": {"type": "object", "required": [], "properties": {}},
        "start": "step_1",
        "steps": [
            {
                "id": "step_1",
                "type": "set_data",
                "config": {"values": {"first": "done"}},
                "next": "step_2",
            },
            {
                "id": "step_2",
                "type": "set_data",
                "config": {"values": {"second": "done"}},
                "next": None,
            },
        ],
    }

    v_resp = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)
    return wf_id, v_resp.json()["id"]


@pytest.mark.asyncio
async def test_cancel_lifecycle_queued_running_and_terminal(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T12: Cancel QUEUED immediately CANCELLED; Cancel RUNNING sets flag & cancels at step boundary; Cancel SUCCEEDED raises 409."""
    _, token = await create_user_and_token(client, "p5t12_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T12 Org"}, headers=headers)
    org_id = org_resp.json()["id"]
    wf_id, _ = await setup_two_step_workflow(client, headers, org_id)

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 1. Cancel QUEUED run -> immediately CANCELLED
    q_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    assert q_resp.status_code == 202
    q_run_id = q_resp.json()["run_id"]

    cancel_q_resp = await client.post(f"/v1/runs/{q_run_id}/cancel", headers=headers)
    assert cancel_q_resp.status_code == 200
    assert cancel_q_resp.json()["state"] == "CANCELLED"
    assert cancel_q_resp.json()["cancel_requested"] is True
    assert cancel_q_resp.json()["finished_at"] is not None

    # 2. Cancel RUNNING run -> sets cancel_requested=true, worker halts at boundary
    r_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    r_run_id = r_resp.json()["run_id"]

    # Simulate step_1 succeeded and run is RUNNING on step_2
    async with session_factory() as session:
        async with session.begin():
            # Step 1 attempt succeeded
            att1 = StepAttempt(
                id=UUID("01a173a4-66f7-74f8-ad69-5d83b8054fa0"),
                run_id=UUID(r_run_id),
                org_id=UUID(org_id),
                step_id="step_1",
                step_type="set_data",
                attempt_no=1,
                status="SUCCEEDED",
                output={"first": "done"},
                epoch=1,
            )
            session.add(att1)
            await session.execute(
                text("""
                    UPDATE workflow_runs
                    SET state = 'RUNNING',
                        lease_owner = 'worker-active-1',
                        lease_expires_at = now() + interval '60 seconds',
                        attempt_epoch = 1,
                        current_step_id = 'step_2'
                    WHERE id = :id
                """),
                {"id": r_run_id},
            )

    cancel_r_resp = await client.post(f"/v1/runs/{r_run_id}/cancel", headers=headers)
    assert cancel_r_resp.status_code == 200
    # On RUNNING, API sets cancel_requested=true, state remains RUNNING until worker processes boundary
    assert cancel_r_resp.json()["state"] == "RUNNING"
    assert cancel_r_resp.json()["cancel_requested"] is True

    # Expire lease so worker can reclaim and hit step_2 boundary with cancel_requested=true
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "UPDATE workflow_runs SET lease_expires_at = now() - interval '1 second' WHERE id = :id"
                ),
                {"id": r_run_id},
            )

    # Now worker claims, notices cancel_requested, and transitions to CANCELLED without running step_2
    await execute_run(UUID(r_run_id), session_factory=session_factory)

    final_r_resp = await client.get(f"/v1/runs/{r_run_id}", headers=headers)
    assert final_r_resp.status_code == 200
    assert final_r_resp.json()["state"] == "CANCELLED"
    assert final_r_resp.json()["finished_at"] is not None

    # Step 1 succeeded before boundary halt, step 2 was never executed
    steps_res = await client.get(f"/v1/runs/{r_run_id}/steps", headers=headers)
    attempts = steps_res.json()["items"]
    assert len(attempts) == 1
    assert attempts[0]["step_id"] == "step_1"
    assert attempts[0]["status"] == "SUCCEEDED"

    # 3. Cancel SUCCEEDED run -> 409 INVALID_STATE_TRANSITION
    s_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    s_run_id = s_resp.json()["run_id"]

    # Run s_run to completion
    await execute_run(UUID(s_run_id), session_factory=session_factory)
    s_detail = await client.get(f"/v1/runs/{s_run_id}", headers=headers)
    assert s_detail.json()["state"] == "SUCCEEDED"

    # Attempt to cancel SUCCEEDED run
    bad_cancel_resp = await client.post(f"/v1/runs/{s_run_id}/cancel", headers=headers)
    assert bad_cancel_resp.status_code == 409
    assert bad_cancel_resp.json()["code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.asyncio
async def test_manual_retry_failed_run_reexecutes_from_failed_step(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T13: POST /v1/runs/{id}/retry on FAILED run -> 202 QUEUED, re-runs only from failed step."""
    _, token = await create_user_and_token(client, "p5t13_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T13 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    # Create 2-step workflow where step_2 is an HTTP step that initially fails
    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "retry_api",
            "provider": "retry_api",
            "secret": "secret",
            "allowed_hosts": ["api.example.com"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Retry From Failed Step Flow",
        "inputs_schema": {"type": "object", "required": [], "properties": {}},
        "start": "step_1",
        "steps": [
            {
                "id": "step_1",
                "type": "set_data",
                "config": {"values": {"step1_output": "cached_ok"}},
                "next": "step_2",
            },
            {
                "id": "step_2",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://api.example.com/v1/action",
                    "credential_id": cred_id,
                    "max_attempts": 1,  # Fails immediately without internal retry
                    "effect": "write",
                },
                "next": None,
            },
        ],
    }

    wf_resp = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Retry Flow"},
        headers=headers,
    )
    wf_id = wf_resp.json()["id"]
    await client.post(
        f"/v1/workflows/{wf_id}/versions", json={"definition": definition}, headers=headers
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)

    run_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = UUID(run_resp.json()["run_id"])

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 1. First run: step_1 succeeds, step_2 fails with 500
    def mock_fail_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "Internal Server Error"})

    fail_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_fail_handler))
    await execute_run(run_id, session_factory=session_factory, http_client=fail_client)

    # Verify run is FAILED
    run_res_1 = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_res_1.json()["state"] == "FAILED"
    assert run_res_1.json()["current_step_id"] == "step_2"

    # Step attempts: step_1 SUCCEEDED, step_2 FAILED
    steps_1 = await client.get(f"/v1/runs/{run_id}/steps", headers=headers)
    items_1 = steps_1.json()["items"]
    assert len(items_1) == 2
    assert items_1[0]["step_id"] == "step_1" and items_1[0]["status"] == "SUCCEEDED"
    assert items_1[1]["step_id"] == "step_2" and items_1[1]["status"] == "FAILED"

    # 2. Retry run via API: POST /v1/runs/{id}/retry
    retry_resp = await client.post(f"/v1/runs/{run_id}/retry", headers=headers)
    assert retry_resp.status_code == 202
    retry_data = retry_resp.json()
    assert retry_data["state"] == "QUEUED"
    assert retry_data["error_code"] is None
    assert retry_data["finished_at"] is None

    # Verify OutboxEvent(RunRequested) was inserted
    async with session_factory() as session:
        evt_res = await session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.aggregate_id == run_id,
                OutboxEvent.event_type == "RunRequested",
            )
            .order_by(OutboxEvent.created_at.desc())
        )
        evt = evt_res.scalars().first()
        assert evt is not None
        assert evt.payload.get("reason") == "manual_retry"

    # 3. Re-execute worker with fixed upstream (200 OK)
    def mock_ok_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "retry_succeeded"})

    ok_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_ok_handler))
    await execute_run(run_id, session_factory=session_factory, http_client=ok_client)

    # Verify run SUCCEEDED
    run_res_2 = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_res_2.json()["state"] == "SUCCEEDED"

    # Step attempts: step_1 has 1 SUCCEEDED attempt; step_2 has 2 attempts (1 FAILED, 1 SUCCEEDED)
    steps_2 = await client.get(f"/v1/runs/{run_id}/steps", headers=headers)
    items_2 = steps_2.json()["items"]
    assert len(items_2) == 3
    # Step 1 was preserved from earlier and not repeated
    assert items_2[0]["step_id"] == "step_1" and items_2[0]["attempt_no"] == 1
    assert (
        items_2[1]["step_id"] == "step_2"
        and items_2[1]["attempt_no"] == 1
        and items_2[1]["status"] == "FAILED"
    )
    assert (
        items_2[2]["step_id"] == "step_2"
        and items_2[2]["attempt_no"] == 2
        and items_2[2]["status"] == "SUCCEEDED"
    )
