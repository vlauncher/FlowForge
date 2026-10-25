#!/usr/bin/env python3
"""Kill-Worker Recovery Drill (P10-S01).

Demonstrates fault-tolerant crash recovery:
1. Launches a 2-step workflow (step_1 -> step_2) with external side effects.
2. Worker 1 starts, executes step 1 (writing tool_effects COMMITTED), and is abruptly killed.
3. Database lease expires; recovery sweeper detects stale lease and schedules recovery.
4. Worker 2 claims run at attempt_epoch=2, skips step 1 due to tool-effects ledger, executes step 2.
5. Verifies exactly 1 external call per step, 0 duplicate effects, and final SUCCEEDED state.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.config import get_settings
from app.infrastructure.db.session import get_session_factory
from app.main import create_app
from app.modules.executions.models import WorkflowRun
from app.modules.integrations.models import ToolEffect
from app.workers.runner import execute_run
from app.workers.sweeper import sweep_stale_and_delayed_runs

GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log(stage: str, msg: str, color: str = BLUE) -> None:
    now = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
    print(f"{BOLD}[{now}] [{color}{stage}{RESET}{BOLD}]{RESET} {msg}")


async def main() -> None:
    print(f"\n{BOLD}=== FlowForge Kill-Worker Recovery Drill (Phase 10) ==={RESET}\n")

    settings = get_settings()
    settings.rate_limit_enabled = False
    app = create_app(settings)
    session_factory = get_session_factory()

    log("SETUP", "Initializing FlowForge client and seeding test workflow...")
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Signup
        email = f"drill_operator_{int(datetime.now(UTC).timestamp())}@example.com"
        su_resp = await client.post(
            "/v1/auth/signup",
            json={"email": email, "password": "Password123456!", "display_name": "Drill Operator"},
        )
        assert su_resp.status_code == 201, f"Signup failed: {su_resp.text}"
        token = su_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create Org
        org_resp = await client.post(
            "/v1/organizations",
            json={"name": "Drill Chaos Inc"},
            headers=headers,
        )
        assert org_resp.status_code == 201
        org_id = org_resp.json()["id"]

        # Create Credential
        cred_resp = await client.post(
            f"/v1/organizations/{org_id}/credentials",
            json={
                "name": "stripe_api",
                "provider": "stripe",
                "secret": "sk_test_drill_chaos",
                "allowed_hosts": ["api.stripe.com"],
            },
            headers=headers,
        )
        assert cred_resp.status_code == 201
        cred_id = cred_resp.json()["id"]

        # 2-Step workflow definition
        definition = {
            "schema_version": 1,
            "name": "Chaos Recovery Workflow",
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
            json={"display_name": "Two-Step Chaos Workflow"},
            headers=headers,
        )
        assert wf_resp.status_code == 201
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

    log("TRIGGER", f"Created run {run_id} in state QUEUED (attempt_epoch=0)", GREEN)

    # Mock server tracking
    external_calls: list[str] = []
    step_1_done = asyncio.Event()
    step_2_started = asyncio.Event()

    async def mock_handler_w1(req: httpx.Request) -> httpx.Response:
        url_str = str(req.url)
        idem = req.headers.get("Idempotency-Key", "none")
        if "customers" in url_str:
            external_calls.append(f"{req.method} {url_str} [Idempotency-Key: {idem}]")
            log("EXTERNAL_MOCK", f"Wire request: {req.method} {url_str}", YELLOW)
            step_1_done.set()
            return httpx.Response(200, json={"id": "cus_drill_live", "status": "active"})
        if "charges" in url_str:
            # Worker 1 reaches step 2; notify main coroutine to kill worker 1 before charge executes
            step_2_started.set()
            await asyncio.sleep(10.0)  # Will be cancelled abruptly
            return httpx.Response(200, json={"id": "unexpected"})
        return httpx.Response(200, json={})

    async def mock_handler_w2(req: httpx.Request) -> httpx.Response:
        url_str = str(req.url)
        idem = req.headers.get("Idempotency-Key", "none")
        external_calls.append(f"{req.method} {url_str} [Idempotency-Key: {idem}]")
        log("EXTERNAL_MOCK", f"Wire request: {req.method} {url_str}", YELLOW)
        if "customers" in url_str:
            return httpx.Response(200, json={"id": "cus_drill_live", "status": "active"})
        if "charges" in url_str:
            return httpx.Response(200, json={"id": "ch_drill_live", "status": "succeeded"})
        return httpx.Response(200, json={})

    mock_client_w1 = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler_w1))
    mock_client_w2 = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler_w2))

    log("WORKER-1", "Starting Worker 1 (worker-drill-1)...", BLUE)
    w1_task = asyncio.create_task(
        execute_run(
            run_id=run_id,
            session_factory=session_factory,
            worker_id="worker-drill-1",
            http_client=mock_client_w1,
        )
    )

    await step_1_done.wait()
    await step_2_started.wait()
    log("CHAOS", "Simulating catastrophic worker kill (SIGKILL / OOM) midway in step 2!", RED)
    w1_task.cancel()
    try:
        await w1_task
    except asyncio.CancelledError:
        pass

    log("WORKER-1", "Worker 1 killed. Lease preserved in DB without clean release.", RED)

    # Verify run state in database
    async with session_factory() as session:
        r_res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        stalled = r_res.scalar_one()
        assert stalled.state == "RUNNING"
        assert stalled.lease_owner == "worker-drill-1"
        assert stalled.attempt_epoch == 1
        log(
            "INVARIANT",
            f"Run state: RUNNING | lease_owner: {stalled.lease_owner} | attempt_epoch: {stalled.attempt_epoch}",
            GREEN,
        )

        # Expire lease to simulate passage of lease_seconds
        await session.execute(
            text("""
                UPDATE workflow_runs
                SET lease_expires_at = now() - interval '2 seconds',
                    updated_at = now() - interval '2 seconds'
                WHERE id = :id
            """),
            {"id": run_id},
        )
        await session.commit()

    log("SWEEPER", "Executing recovery sweeper to detect expired leases...", BLUE)
    recovered = await sweep_stale_and_delayed_runs(session_factory)
    log("SWEEPER", f"Sweeper recovered {recovered} stale run(s); queued RunResumeRequested.", GREEN)

    log("WORKER-2", "Starting Worker 2 (worker-drill-2) to reclaim and resume execution...", BLUE)
    await execute_run(
        run_id=run_id,
        session_factory=session_factory,
        worker_id="worker-drill-2",
        http_client=mock_client_w2,
    )

    # Verification
    async with session_factory() as session:
        final_res = await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        final = final_res.scalar_one()
        assert final.state == "SUCCEEDED"
        assert final.attempt_epoch == 2
        log(
            "OUTCOME",
            f"Final Run State: {final.state} | Final attempt_epoch: {final.attempt_epoch}",
            GREEN,
        )

        effs = (
            (await session.execute(select(ToolEffect).where(ToolEffect.run_id == run_id)))
            .scalars()
            .all()
        )
        assert len(effs) == 2
        assert all(e.state == "COMMITTED" for e in effs)
        log("OUTCOME", f"Committed Tool Effects: {len(effs)}/2 steps verified", GREEN)

    log("VERIFICATION", f"Total external wire calls recorded: {len(external_calls)}", BLUE)
    for c in external_calls:
        print(f"  -> {c}")
    assert len(external_calls) == 2, f"Expected exactly 2 wire calls, got {len(external_calls)}"
    print(
        f"\n{GREEN}{BOLD}✔ DRILL SUCCESS: 0 duplicate side effects, successful lease takeover at epoch 2!{RESET}\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
