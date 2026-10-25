"""E2E recovery drills: kill-worker recovery, duplicate delivery no-op, and runbooks check.

Covers:
- P10-T01: Automated kill-worker scenario completes SUCCEEDED with attempt_epoch == 2 and 0 duplicate external side effects.
- P10-T02: Replay + cancel drill: duplicate outbox event delivery after run is CANCELLED or SUCCEEDED is a strict no-op.
- P10-T03: Runbooks & gate evidence check: all 8 runbooks, 5 ADRs, threat model, postmortem, and case study exist and contain required headings.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
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
async def test_p10_t01_kill_worker_recovery(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P10-T01: Kill worker during step transition; sweeper + worker 2 recover run to SUCCEEDED with 0 duplicate effects."""
    _, token = await create_user_and_token(client, "p10t01_user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Org & Credentials
    org_resp = await client.post("/v1/organizations", json={"name": "P10T01 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "stripe_api",
            "provider": "stripe",
            "secret": "sk_test_p10t01_secret",
            "allowed_hosts": ["api.stripe.com"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    # 2. Define 2-step workflow: step_1 -> step_2
    definition = {
        "schema_version": 1,
        "name": "Two Step Kill Recovery Workflow",
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
        json={"display_name": "Kill Recovery Workflow"},
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
    assert run_resp.status_code in (201, 202)
    run_id = UUID(run_resp.json()["run_id"])

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 3. Track calls to mock server
    mock_calls: list[dict[str, str]] = []

    def mock_server_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        idem_key = request.headers.get("Idempotency-Key", "none")
        mock_calls.append({"url": url_str, "idempotency_key": idem_key})

        if "customers" in url_str:
            return httpx.Response(200, json={"id": "cus_drill_123", "status": "active"})
        if "charges" in url_str:
            return httpx.Response(200, json={"id": "ch_drill_456", "status": "paid"})
        return httpx.Response(200, json={})

    mock_http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_server_handler))

    # 4. Worker 1 starts and executes step 1, but is forcefully killed/cancelled before step 2 finishes
    # We simulate this by having worker 1 execute step 1 and crash immediately after step 1 tool_effect is COMMITTED
    step_1_done_event = asyncio.Event()

    def crashing_mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        idem_key = request.headers.get("Idempotency-Key", "none")
        mock_calls.append({"url": url_str, "idempotency_key": idem_key})
        if "customers" in url_str:
            step_1_done_event.set()
            return httpx.Response(200, json={"id": "cus_drill_123", "status": "active"})
        # Should not reach here because task gets cancelled after step 1
        return httpx.Response(200, json={"id": "unexpected"})

    crashing_client = httpx.AsyncClient(transport=httpx.MockTransport(crashing_mock_handler))

    # Run Worker 1 in background task and cancel it immediately after step 1 commits
    worker_1_task = asyncio.create_task(
        execute_run(
            run_id=run_id,
            session_factory=session_factory,
            worker_id="worker-crash-1",
            http_client=crashing_client,
        )
    )

    await step_1_done_event.wait()
    # Give a brief moment for the DB commit of step 1 tool effect
    await asyncio.sleep(0.05)

    # Forcefully cancel Worker 1 task without letting it finish or release lease
    worker_1_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker_1_task

    # 5. Assert run is RUNNING with lease_owner = worker-crash-1, attempt_epoch = 1
    async with session_factory() as session:
        r_res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        stalled_run = r_res.scalar_one()
        assert stalled_run.state == "RUNNING"
        assert stalled_run.lease_owner == "worker-crash-1"
        assert stalled_run.attempt_epoch == 1

        # Check step 1 tool effect is COMMITTED
        eff_res = await session.execute(
            select(ToolEffect).where(ToolEffect.run_id == run_id, ToolEffect.step_id == "step_1")
        )
        eff1 = eff_res.scalar_one()
        assert eff1.state == "COMMITTED"
        assert eff1.response_summary["body"]["id"] == "cus_drill_123"

        # Simulate lease expiration (time passes)
        await session.execute(
            text("""
                UPDATE workflow_runs
                SET lease_expires_at = now() - interval '5 seconds',
                    updated_at = now() - interval '5 seconds'
                WHERE id = :id
            """),
            {"id": run_id},
        )
        await session.commit()

    # 6. Sweeper runs and reclaims stale lease
    recovered = await sweep_stale_and_delayed_runs(session_factory)
    assert recovered == 1

    # Verify RunResumeRequested outbox event created
    async with session_factory() as session:
        evt_res = await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == run_id,
                OutboxEvent.event_type == "RunResumeRequested",
            )
        )
        assert evt_res.scalar_one_or_none() is not None

    # Clear mock calls record so we can verify exact calls made by worker 2
    mock_calls.clear()

    # 7. Worker 2 starts and executes run to completion
    await execute_run(
        run_id=run_id,
        session_factory=session_factory,
        worker_id="worker-recover-2",
        http_client=mock_http_client,
    )

    # 8. Assertions:
    # - Worker 2 skipped step 1 (checked tool-effects ledger)
    # - Worker 2 executed step 2 exactly once
    assert len(mock_calls) == 1
    assert "charges" in mock_calls[0]["url"]

    # - Run reaches state = 'SUCCEEDED' with attempt_epoch == 2
    async with session_factory() as session:
        final_res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        final_run = final_res.scalar_one()
        assert final_run.state == "SUCCEEDED"
        assert final_run.attempt_epoch == 2
        assert final_run.lease_owner is None
        assert final_run.context["step_1"]["body"]["id"] == "cus_drill_123"
        assert final_run.context["step_2"]["body"]["id"] == "ch_drill_456"


@pytest.mark.asyncio
async def test_p10_t02_replay_cancel_drill(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P10-T02: Duplicate outbox event delivery after run is CANCELLED or SUCCEEDED is a strict no-op."""
    _, token = await create_user_and_token(client, "p10t02_user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P10T02 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "stripe_api",
            "provider": "stripe",
            "secret": "sk_test_p10t02",
            "allowed_hosts": ["api.stripe.com"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Single Step Flow",
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
                "next": None,
            }
        ],
    }

    wf_resp = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Replay Flow"},
        headers=headers,
    )
    wf_id = wf_resp.json()["id"]

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    call_count = 0

    def mock_handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"id": f"cus_{call_count}"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    # --- Scenario A: Run succeeds, subsequent execute_run is strict no-op ---
    run_a_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_a_id = UUID(run_a_resp.json()["run_id"])

    await execute_run(run_a_id, session_factory=session_factory, http_client=mock_client)
    assert call_count == 1

    # Verify run state is SUCCEEDED
    async with session_factory() as session:
        r_a = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_a_id))
        ).scalar_one()
        assert r_a.state == "SUCCEEDED"
        epoch_a = r_a.attempt_epoch

    # Re-trigger execute_run on SUCCEEDED run (simulating duplicate outbox message replay)
    await execute_run(run_a_id, session_factory=session_factory, http_client=mock_client)

    # Assert no new external calls, state unchanged, attempt_epoch unchanged
    assert call_count == 1
    async with session_factory() as session:
        r_a_replayed = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_a_id))
        ).scalar_one()
        assert r_a_replayed.state == "SUCCEEDED"
        assert r_a_replayed.attempt_epoch == epoch_a

    # --- Scenario B: Run is CANCELLED, execute_run is strict no-op ---
    run_b_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_b_id = UUID(run_b_resp.json()["run_id"])

    # Manually transition run to CANCELLED
    async with session_factory() as session:
        await session.execute(
            text("""
                UPDATE workflow_runs
                SET state = 'CANCELLED',
                    cancel_requested = TRUE,
                    updated_at = now()
                WHERE id = :id
            """),
            {"id": run_b_id},
        )
        await session.commit()

    # Re-trigger execute_run on CANCELLED run
    await execute_run(run_b_id, session_factory=session_factory, http_client=mock_client)

    # Assert no external calls made, state remains CANCELLED
    assert call_count == 1
    async with session_factory() as session:
        r_b_replayed = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_b_id))
        ).scalar_one()
        assert r_b_replayed.state == "CANCELLED"


def test_p10_t03_runbooks_and_gate_evidence_check() -> None:
    """P10-T03: All 8 runbooks, 5 ADRs, threat model, postmortem, and case study exist and contain required headings."""
    root = Path(__file__).resolve().parent.parent.parent
    docs = root / "docs"

    # 1. Check all 8 runbooks
    expected_runbooks = [
        "01-provider-429-storm.md",
        "02-stuck-running-task.md",
        "03-approval-expired.md",
        "04-webhook-signature-mismatch.md",
        "05-queue-saturation.md",
        "06-secret-compromise.md",
        "07-billing-overspend.md",
        "08-db-restore.md",
    ]
    required_runbook_headings = [
        "## 1. Symptom & Alert",
        "## 2. Impact",
        "## 3. Detection & Diagnosis Queries",
        "## 4. Containment & Safe Recovery Steps",
        "## 5. Escalation & Prevention",
    ]

    for rb_name in expected_runbooks:
        rb_path = docs / "runbooks" / rb_name
        assert rb_path.exists(), f"Runbook {rb_name} is missing"
        rb_text = rb_path.read_text(encoding="utf-8")
        for heading in required_runbook_headings:
            assert heading in rb_text, f"Runbook {rb_name} missing required heading '{heading}'"

    # 2. Check 5 ADRs
    expected_adrs = [
        "ADR-001-modular-monolith.md",
        "ADR-002-tenant-isolation.md",
        "ADR-003-custom-state-machine.md",
        "ADR-004-duplicate-delivery.md",
        "ADR-005-prompt-injection-defense.md",
    ]
    for adr_name in expected_adrs:
        adr_path = docs / "adr" / adr_name
        assert adr_path.exists(), f"ADR {adr_name} is missing"

    # 3. Check Threat Model
    assert (docs / "threat-model.md").exists(), "docs/threat-model.md is missing"

    # 4. Check Postmortem
    pm_path = docs / "postmortems" / "PM-001-worker-lease-stall.md"
    assert pm_path.exists(), "PM-001-worker-lease-stall.md is missing"
    pm_text = pm_path.read_text(encoding="utf-8")
    assert "Root Cause Analysis" in pm_text
    assert "Action Items" in pm_text

    # 5. Check Architecture & Scaling Proposal
    assert (docs / "architecture" / "10x-scaling-proposal.md").exists(), (
        "10x-scaling-proposal.md is missing"
    )
    assert (docs / "architecture" / "diagrams.md").exists(), "diagrams.md is missing"

    # 6. Check Case Study and G1-G6 matrix
    cs_path = docs / "case-study.md"
    assert cs_path.exists(), "docs/case-study.md is missing"
    cs_text = cs_path.read_text(encoding="utf-8")
    for gate in [
        "G1: Specification",
        "G2: Data Correctness",
        "G3: Security",
        "G4: Recovery",
        "G5: Operations",
        "G6: Communication",
    ]:
        assert gate in cs_text, f"Case study missing gate '{gate}'"
