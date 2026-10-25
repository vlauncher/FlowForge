"""Integration tests for HTTP tool adapter, tool effects ledger, and error handling (P5-T05 to P5-T10)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.integrations.models import ToolEffect
from app.workers.runner import execute_run


async def create_user_and_token(client: AsyncClient, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["user"]["id"], data["access_token"]


async def setup_test_workflow(
    client: AsyncClient,
    owner_headers: dict[str, str],
    org_id: str,
    step_config: dict[str, Any],
) -> tuple[str, str]:
    """Helper to create and publish a 1-step HTTP workflow."""
    wf_resp = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "HTTP Test Flow"},
        headers=owner_headers,
    )
    assert wf_resp.status_code == 201
    wf_id = wf_resp.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "HTTP Test Flow",
        "inputs_schema": {
            "type": "object",
            "required": [],
            "properties": {},
        },
        "start": "http_step",
        "steps": [
            {
                "id": "http_step",
                "type": "http_request",
                "config": step_config,
                "next": None,
            }
        ],
    }

    v_resp = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=owner_headers,
    )
    assert v_resp.status_code == 201

    pub_resp = await client.post(f"/v1/workflows/{wf_id}/publish", headers=owner_headers)
    assert pub_resp.status_code == 200

    return wf_id, v_resp.json()["id"]


@pytest.mark.asyncio
async def test_http_tool_success_ledger_committed_and_header_redaction(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T05: http_request to allowlisted mock server succeeds, commits ledger, injects headers, redacts secrets."""
    _, token = await create_user_and_token(client, "p5t05_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T05 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    # 1. Create integration credential
    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "stripe_api",
            "provider": "stripe",
            "secret": "sk_test_p5t05_secret_key",
            "allowed_hosts": ["api.stripe.com"],
            "permission_scopes": ["charges:write"],
        },
        headers=headers,
    )
    assert cred_resp.status_code == 201
    cred_id = cred_resp.json()["id"]

    # 2. Setup workflow
    step_cfg = {
        "method": "POST",
        "url": "https://api.stripe.com/v1/charges",
        "credential_id": cred_id,
        "body": {"amount": 2000, "currency": "usd"},
        "timeout_seconds": 10,
        "effect": "write",
        "max_attempts": 3,
        "provider_supports_idempotency": True,
    }
    wf_id, _ = await setup_test_workflow(client, headers, org_id, step_cfg)

    # 3. Trigger run
    run_resp = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {}},
        headers=headers,
    )
    assert run_resp.status_code == 202
    run_id = UUID(run_resp.json()["run_id"])

    # 4. Mock HTTP Transport
    captured_requests: list[httpx.Request] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            201,
            json={"id": "ch_123456", "status": "succeeded"},
            headers={"Content-Type": "application/json"},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Execute worker
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)

    # 5. Verify run SUCCEEDED
    run_detail_resp = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_detail_resp.status_code == 200
    run_detail = run_detail_resp.json()
    assert run_detail["state"] == "SUCCEEDED"
    assert run_detail["outputs"]["body"]["id"] == "ch_123456"

    # 6. Verify request headers sent
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.headers["Idempotency-Key"] == f"{run_id}:http_step"
    assert req.headers["Authorization"] == "Bearer sk_test_p5t05_secret_key"
    assert "X-Request-ID" in req.headers

    # 7. Verify tool_effects row in DB is COMMITTED
    async with session_factory() as session:
        te_res = await session.execute(
            select(ToolEffect).where(
                ToolEffect.provider == "stripe",
                ToolEffect.idempotency_key == f"{run_id}:http_step",
            )
        )
        effect = te_res.scalar_one_or_none()
        assert effect is not None
        assert effect.state == "COMMITTED"
        assert effect.external_ref == "ch_123456"

    # 8. Verify step_attempts input redacts any secret
    att_resp = await client.get(f"/v1/runs/{run_id}/steps", headers=headers)
    assert att_resp.status_code == 200
    attempts = att_resp.json()["items"]
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["status"] == "SUCCEEDED"
    # The credential secret must not be in attempt input
    assert "sk_test_p5t05_secret_key" not in str(attempt["input"])


@pytest.mark.asyncio
async def test_reexecuting_committed_step_makes_zero_http_requests(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T06: Re-executing a step whose tool_effects is already COMMITTED returns summary with 0 HTTP calls."""
    _, token = await create_user_and_token(client, "p5t06_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T06 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "stripe_api",
            "provider": "stripe",
            "secret": "sk_test_p5t06",
            "allowed_hosts": ["api.stripe.com"],
            "permission_scopes": ["charges:write"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    step_cfg = {
        "method": "POST",
        "url": "https://api.stripe.com/v1/charges",
        "credential_id": cred_id,
        "body": {"amount": 5000},
        "timeout_seconds": 10,
        "effect": "write",
    }
    wf_id, _ = await setup_test_workflow(client, headers, org_id, step_cfg)

    run_resp = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {}},
        headers=headers,
    )
    run_id = UUID(run_resp.json()["run_id"])

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Insert pre-existing COMMITTED tool_effects row
    async with session_factory() as session:
        async with session.begin():
            effect = ToolEffect(
                org_id=UUID(org_id),
                run_id=run_id,
                step_id="http_step",
                provider="stripe",
                idempotency_key=f"{run_id}:http_step",
                state="COMMITTED",
                request_hash="mock_hash",
                external_ref="ch_precommitted_999",
                response_summary={
                    "status": 200,
                    "body": {"id": "ch_precommitted_999", "status": "replayed"},
                    "headers": {},
                },
            )
            session.add(effect)

    # Mock handler that counts requests
    request_count = 0

    def mock_handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"id": "unexpected"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    # Execute run
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)

    # Assert 0 HTTP calls were made
    assert request_count == 0

    # Verify run succeeded using the committed summary
    run_detail_resp = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_detail_resp.status_code == 200
    assert run_detail_resp.json()["state"] == "SUCCEEDED"
    assert run_detail_resp.json()["outputs"]["body"]["id"] == "ch_precommitted_999"


@pytest.mark.asyncio
async def test_upstream_503_retries_and_succeeds_on_attempt_3(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T07: Upstream returns 503 twice then 200 on attempt 3 -> 3 step_attempts rows and run SUCCEEDED."""
    _, token = await create_user_and_token(client, "p5t07_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T07 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "stripe_api",
            "provider": "stripe",
            "secret": "sk_test_p5t07",
            "allowed_hosts": ["api.stripe.com"],
            "permission_scopes": ["charges:write"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    step_cfg = {
        "method": "POST",
        "url": "https://api.stripe.com/v1/charges",
        "credential_id": cred_id,
        "max_attempts": 3,
        "effect": "write",
    }
    wf_id, _ = await setup_test_workflow(client, headers, org_id, step_cfg)

    run_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = UUID(run_resp.json()["run_id"])

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    call_index = 0

    def mock_handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_index
        call_index += 1
        if call_index in (1, 2):
            return httpx.Response(503, json={"error": "Service Unavailable"})
        return httpx.Response(200, json={"id": "ch_success_attempt_3"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    # Helper to advance next_attempt_at so worker can claim
    async def reset_next_attempt() -> None:
        async with session_factory() as s:
            async with s.begin():
                await s.execute(
                    text("UPDATE workflow_runs SET next_attempt_at = now() WHERE id = :id"),
                    {"id": run_id},
                )

    # Attempt 1 -> 503, queues for retry
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)
    run_1 = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_1.json()["state"] == "QUEUED"

    # Attempt 2 -> 503, queues for retry
    await reset_next_attempt()
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)
    run_2 = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_2.json()["state"] == "QUEUED"

    # Attempt 3 -> 200, succeeds
    await reset_next_attempt()
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)
    run_3 = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_3.json()["state"] == "SUCCEEDED"

    # Verify 3 step_attempts rows: FAILED, FAILED, SUCCEEDED
    steps_resp = await client.get(f"/v1/runs/{run_id}/steps", headers=headers)
    attempts = steps_resp.json()["items"]
    assert len(attempts) == 3
    assert attempts[0]["attempt_no"] == 1 and attempts[0]["status"] == "FAILED"
    assert attempts[1]["attempt_no"] == 2 and attempts[1]["status"] == "FAILED"
    assert attempts[2]["attempt_no"] == 3 and attempts[2]["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_upstream_503_retries_exhausted_ends_failed(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T08: Upstream returns 503 on all max_attempts=3 -> run ends FAILED with STEP_RETRIES_EXHAUSTED."""
    _, token = await create_user_and_token(client, "p5t08_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T08 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "stripe_api",
            "provider": "stripe",
            "secret": "sk_test_p5t08",
            "allowed_hosts": ["api.stripe.com"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    step_cfg = {
        "method": "POST",
        "url": "https://api.stripe.com/v1/charges",
        "credential_id": cred_id,
        "max_attempts": 3,
        "effect": "write",
    }
    wf_id, _ = await setup_test_workflow(client, headers, org_id, step_cfg)

    run_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = UUID(run_resp.json()["run_id"])

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    def mock_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "Downstream Down"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    async def reset_next_attempt() -> None:
        async with session_factory() as s:
            async with s.begin():
                await s.execute(
                    text("UPDATE workflow_runs SET next_attempt_at = now() WHERE id = :id"),
                    {"id": run_id},
                )

    # Attempt 1
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)
    # Attempt 2
    await reset_next_attempt()
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)
    # Attempt 3 (final)
    await reset_next_attempt()
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)

    run_res = await client.get(f"/v1/runs/{run_id}", headers=headers)
    run_data = run_res.json()
    assert run_data["state"] == "FAILED"
    assert run_data["error_code"] == "STEP_RETRIES_EXHAUSTED"


@pytest.mark.asyncio
async def test_timeout_on_non_idempotent_write_sets_ambiguous_and_halts(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T09: ReadTimeout on effect='write' with provider_supports_idempotency=False sets AMBIGUOUS and halts."""
    _, token = await create_user_and_token(client, "p5t09_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T09 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "legacy_gateway",
            "provider": "legacy_gateway",
            "secret": "legacy_secret",
            "allowed_hosts": ["legacy.example.com"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    step_cfg = {
        "method": "POST",
        "url": "https://legacy.example.com/v1/charge",
        "credential_id": cred_id,
        "effect": "write",
        "provider_supports_idempotency": False,
        "max_attempts": 3,
    }
    wf_id, _ = await setup_test_workflow(client, headers, org_id, step_cfg)

    run_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = UUID(run_resp.json()["run_id"])

    call_count = 0

    def mock_handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("Server dropped connection after processing bytes")

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    # First attempt triggers ReadTimeout
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)

    # Verify tool_effects row is AMBIGUOUS
    async with session_factory() as session:
        res = await session.execute(
            select(ToolEffect).where(
                ToolEffect.provider == "legacy_gateway",
                ToolEffect.idempotency_key == f"{run_id}:http_step",
            )
        )
        eff = res.scalar_one()
        assert eff.state == "AMBIGUOUS"

    # Verify run state is FAILED with TOOL_EFFECT_AMBIGUOUS
    run_res = await client.get(f"/v1/runs/{run_id}", headers=headers)
    assert run_res.json()["state"] == "FAILED"
    assert run_res.json()["error_code"] == "TOOL_EFFECT_AMBIGUOUS"

    # Verify that a retry or re-execution does NOT make a 2nd POST
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)
    assert call_count == 1


@pytest.mark.asyncio
async def test_egress_check_blocks_disallowed_host(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P5-T10: Request to host not in allowed_hosts fails immediately on attempt 1 with EGRESS_BLOCKED."""
    _, token = await create_user_and_token(client, "p5t10_owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_resp = await client.post("/v1/organizations", json={"name": "P5T10 Org"}, headers=headers)
    org_id = org_resp.json()["id"]

    cred_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "name": "strict_cred",
            "provider": "strict",
            "secret": "strict_secret",
            "allowed_hosts": ["api.allowed.com"],
        },
        headers=headers,
    )
    cred_id = cred_resp.json()["id"]

    # Step points to evil-attacker.com instead of api.allowed.com
    step_cfg = {
        "method": "POST",
        "url": "https://evil-attacker.com/leak",
        "credential_id": cred_id,
        "max_attempts": 3,
    }
    wf_id, _ = await setup_test_workflow(client, headers, org_id, step_cfg)

    run_resp = await client.post(f"/v1/workflows/{wf_id}/runs", json={}, headers=headers)
    run_id = UUID(run_resp.json()["run_id"])

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )

    call_made = False

    def mock_handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_made
        call_made = True
        return httpx.Response(200, json={"status": "leaked"})

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    # Run worker
    await execute_run(run_id, session_factory=session_factory, http_client=mock_client)

    # Verify no HTTP request was made
    assert not call_made

    # Verify run is FAILED with EGRESS_BLOCKED
    run_res = await client.get(f"/v1/runs/{run_id}", headers=headers)
    run_data = run_res.json()
    assert run_data["state"] == "FAILED"
    assert run_data["error_code"] == "EGRESS_BLOCKED"

    # Verify attempt recorded as FAILED and not retryable
    steps_resp = await client.get(f"/v1/runs/{run_id}/steps", headers=headers)
    attempts = steps_resp.json()["items"]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "FAILED"
    assert attempts[0]["retryable"] is False
