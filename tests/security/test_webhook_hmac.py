"""Webhook HMAC signature and replay security tests (P9-T04, P9-T05)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.executions.models import WorkflowRun


async def signup_and_setup(client: AsyncClient) -> tuple[str, str, str, str, str]:
    """Helper to sign up user, create org, credential, and published workflow."""
    # 1. Signup
    signup_res = await client.post(
        "/v1/auth/signup",
        json={
            "email": "webhook_owner@example.com",
            "password": "Password123456!",
            "display_name": "Webhook Owner",
        },
    )
    token = signup_res.json()["access_token"]
    auth_header = {"Authorization": f"Bearer {token}"}

    # 2. Org
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Webhook Org", "slug": "webhook-org"},
        headers=auth_header,
    )
    org_id = org_res.json()["id"]

    # 3. Credential (shared secret)
    secret_text = "my-webhook-secret-token-123456"
    cred_res = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json={
            "provider": "webhook_provider",
            "name": "Webhook Secret",
            "secret": secret_text,
            "allowed_hosts": ["example.com"],
        },
        headers=auth_header,
    )
    cred_id = cred_res.json()["id"]

    # 4. Workflow
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Webhook Target Workflow"},
        headers=auth_header,
    )
    wf_id = wf_res.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Webhook Flow",
        "inputs_schema": {
            "type": "object",
            "required": ["event_type"],
            "properties": {"event_type": {"type": "string"}},
        },
        "start": "step_one",
        "steps": [
            {
                "id": "step_one",
                "type": "set_data",
                "config": {"values": {"received": "{{ inputs.event_type }}"}},
                "next": None,
            }
        ],
    }

    # Add version and publish
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=auth_header,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=auth_header)

    return token, org_id, cred_id, wf_id, secret_text


def compute_signature(secret: str, timestamp: int, body_bytes: bytes) -> str:
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode() + body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"v1={mac}"


@pytest.mark.asyncio
async def test_p9_t04_webhook_signature_and_timestamp_verification(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P9-T04: Valid HMAC + fresh timestamp -> 202 and 1 run; invalid sig -> 401; old ts -> 401."""
    token, org_id, cred_id, wf_id, secret = await signup_and_setup(client)
    auth_header = {"Authorization": f"Bearer {token}"}

    # Create trigger
    trigger_res = await client.post(
        f"/v1/workflows/{wf_id}/triggers",
        json={"credential_id": cred_id},
        headers=auth_header,
    )
    assert trigger_res.status_code == 201
    trigger_data = trigger_res.json()
    trigger_id = trigger_data["id"]

    body = json.dumps({"event_type": "user_signup"}).encode("utf-8")
    now_ts = int(time.time())

    # 1. Valid signature + fresh timestamp -> 202
    sig = compute_signature(secret, now_ts, body)
    headers = {
        "Content-Type": "application/json",
        "X-FlowForge-Timestamp": str(now_ts),
        "X-FlowForge-Signature": sig,
    }
    resp = await client.post(
        f"/v1/triggers/webhooks/{trigger_id}",
        content=body,
        headers=headers,
    )
    assert resp.status_code == 202
    assert resp.headers.get("Location")
    assert resp.headers.get("Idempotency-Replayed") is None

    # Check 1 run created
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workflow_id == UUID(wf_id))
        )
        assert count == 1

    # 2. Invalid signature -> 401 WEBHOOK_SIGNATURE_INVALID
    bad_headers = {
        "Content-Type": "application/json",
        "X-FlowForge-Timestamp": str(now_ts),
        "X-FlowForge-Signature": "v1=0000000000000000000000000000000000000000000000000000000000000000",
    }
    resp_bad = await client.post(
        f"/v1/triggers/webhooks/{trigger_id}",
        content=body,
        headers=bad_headers,
    )
    assert resp_bad.status_code == 401
    assert resp_bad.json()["code"] == "WEBHOOK_SIGNATURE_INVALID"

    # 3. Timestamp 600s old -> 401 WEBHOOK_REPLAY
    old_ts = now_ts - 600
    old_sig = compute_signature(secret, old_ts, body)
    old_headers = {
        "Content-Type": "application/json",
        "X-FlowForge-Timestamp": str(old_ts),
        "X-FlowForge-Signature": old_sig,
    }
    resp_old = await client.post(
        f"/v1/triggers/webhooks/{trigger_id}",
        content=body,
        headers=old_headers,
    )
    assert resp_old.status_code == 401
    assert resp_old.json()["code"] == "WEBHOOK_REPLAY"


@pytest.mark.asyncio
async def test_p9_t05_webhook_replay_deduplication(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P9-T05: Duplicate delivery of identical signed webhook returns 202 with Idempotency-Replayed: true."""
    token, org_id, cred_id, wf_id, secret = await signup_and_setup(client)
    auth_header = {"Authorization": f"Bearer {token}"}

    # Create trigger
    trigger_res = await client.post(
        f"/v1/workflows/{wf_id}/triggers",
        json={"credential_id": cred_id},
        headers=auth_header,
    )
    trigger_id = trigger_res.json()["id"]

    body = json.dumps({"event_type": "order_placed"}).encode("utf-8")
    now_ts = int(time.time())
    sig = compute_signature(secret, now_ts, body)
    headers = {
        "Content-Type": "application/json",
        "X-FlowForge-Timestamp": str(now_ts),
        "X-FlowForge-Signature": sig,
    }

    # First delivery
    resp1 = await client.post(
        f"/v1/triggers/webhooks/{trigger_id}",
        content=body,
        headers=headers,
    )
    assert resp1.status_code == 202
    assert resp1.headers.get("Idempotency-Replayed") is None
    run_id1 = resp1.json()["run_id"]

    # Second delivery (identical)
    resp2 = await client.post(
        f"/v1/triggers/webhooks/{trigger_id}",
        content=body,
        headers=headers,
    )
    assert resp2.status_code == 202
    assert resp2.headers.get("Idempotency-Replayed") == "true"
    run_id2 = resp2.json()["run_id"]

    assert run_id1 == run_id2

    # Verify no second run was inserted
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workflow_id == UUID(wf_id))
        )
        assert count == 1
