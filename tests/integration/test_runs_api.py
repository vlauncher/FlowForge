"""Integration tests for workflow runs API, idempotency, and concurrency limits (P4-T03 to P4-T06, P4-T12)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.executions.models import OutboxEvent, WorkflowRun


async def get_auth_token(client: AsyncClient, email: str) -> str:
    signup_res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return signup_res.json()["access_token"]


def valid_flow_definition() -> dict:
    return {
        "schema_version": 1,
        "name": "Order Process",
        "inputs_schema": {
            "type": "object",
            "required": ["order_id", "amount"],
            "properties": {
                "order_id": {"type": "string"},
                "amount": {"type": "number", "minimum": 1},
            },
            "additionalProperties": False,
        },
        "start": "step_init",
        "steps": [
            {
                "id": "step_init",
                "type": "set_data",
                "config": {"values": {"ref": "{{ inputs.order_id }}", "status": "initialized"}},
                "next": None,
            }
        ],
    }


async def setup_org_and_published_workflow(
    client: AsyncClient, email: str = "creator@example.com"
) -> tuple[dict[str, str], str, str]:
    """Helper creating an org, a workflow, and publishing v1."""
    token = await get_auth_token(client, email)
    headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post(
        "/v1/organizations", json={"name": "Execution Org"}, headers=headers
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Test Run Flow"},
        headers=headers,
    )
    wf_id = wf_res.json()["id"]

    # Create draft v1
    v1_res = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_flow_definition()},
        headers=headers,
    )
    assert v1_res.status_code == 201

    # Publish v1
    pub_res = await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)
    assert pub_res.status_code == 200

    return headers, org_id, wf_id


@pytest.mark.asyncio
async def test_trigger_run_creates_queued_and_outbox(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    """P4-T03: POST /v1/workflows/{id}/runs returns 202 and persists run(QUEUED) + outbox(unpublished)."""
    headers, org_id, wf_id = await setup_org_and_published_workflow(client)

    payload = {"inputs": {"order_id": "ORD-123", "amount": 99.5}}
    res = await client.post(f"/v1/workflows/{wf_id}/runs", json=payload, headers=headers)
    assert res.status_code == 202
    data = res.json()
    run_id = data["run_id"]
    assert data["state"] == "QUEUED"
    assert data["workflow_version"] == 1
    assert res.headers.get("Location") == f"/v1/runs/{run_id}"

    # Verify database state
    factory = async_sessionmaker(bind=db_engine)
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.state == "QUEUED"
        assert run.inputs == {"order_id": "ORD-123", "amount": 99.5}

        outbox_stmt = select(OutboxEvent).where(OutboxEvent.aggregate_id == run_id)
        outbox_res = await session.execute(outbox_stmt)
        outbox = outbox_res.scalar_one_or_none()
        assert outbox is not None
        assert outbox.event_type == "RunRequested"
        assert outbox.published_at is None
        assert outbox.payload["run_id"] == str(run_id)


@pytest.mark.asyncio
async def test_idempotency_key_replay_and_mismatch(client: AsyncClient) -> None:
    """P4-T04: Same Idempotency-Key + same body returns 202 with Idempotency-Replayed: true; different body returns 409."""
    headers, org_id, wf_id = await setup_org_and_published_workflow(client, "idemp@example.com")

    idemp_headers = {**headers, "Idempotency-Key": "req-key-001"}
    payload_a = {"inputs": {"order_id": "ORD-1", "amount": 50}}

    # First request
    res1 = await client.post(f"/v1/workflows/{wf_id}/runs", json=payload_a, headers=idemp_headers)
    assert res1.status_code == 202
    assert "Idempotency-Replayed" not in res1.headers
    run_id_1 = res1.json()["run_id"]

    # Replayed identical request
    res2 = await client.post(f"/v1/workflows/{wf_id}/runs", json=payload_a, headers=idemp_headers)
    assert res2.status_code == 202
    assert res2.headers.get("Idempotency-Replayed") == "true"
    assert res2.json()["run_id"] == run_id_1

    # Conflict with same key but different payload
    payload_b = {"inputs": {"order_id": "ORD-DIFFERENT", "amount": 500}}
    res3 = await client.post(f"/v1/workflows/{wf_id}/runs", json=payload_b, headers=idemp_headers)
    assert res3.status_code == 409
    assert res3.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_unpublished_workflow_and_invalid_schema_inputs(client: AsyncClient) -> None:
    """P4-T05: Triggering workflow with no published version -> 409; invalid inputs -> 422."""
    token = await get_auth_token(client, "schema_test@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post("/v1/organizations", json={"name": "Schema Org"}, headers=headers)
    org_id = org_res.json()["id"]

    # Unpublished workflow shell
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Unpublished Flow"},
        headers=headers,
    )
    wf_id = wf_res.json()["id"]

    # Trigger before publish -> 409 VERSION_NOT_PUBLISHED
    res_unpub = await client.post(
        f"/v1/workflows/{wf_id}/runs", json={"inputs": {}}, headers=headers
    )
    assert res_unpub.status_code == 409
    assert res_unpub.json()["code"] == "VERSION_NOT_PUBLISHED"

    # Now create and publish version with strict schema
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_flow_definition()},
        headers=headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)

    # Invalid input (missing order_id, amount < 1) -> 422 VALIDATION_ERROR
    bad_payload = {"inputs": {"amount": 0}}
    res_bad = await client.post(f"/v1/workflows/{wf_id}/runs", json=bad_payload, headers=headers)
    assert res_bad.status_code == 422
    assert res_bad.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_concurrency_limit_exceeded(client: AsyncClient, db_engine: AsyncEngine) -> None:
    """P4-T06: When active runs reach org max_concurrent_runs, subsequent requests return 429."""
    headers, org_id, wf_id = await setup_org_and_published_workflow(client, "concur@example.com")

    # Set org max_concurrent_runs = 2 directly in DB
    async with db_engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE organizations SET max_concurrent_runs = 2 WHERE id = '{org_id}'")
        )

    # Trigger run 1 -> 202
    res1 = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"order_id": "ORD-1", "amount": 10}},
        headers=headers,
    )
    assert res1.status_code == 202

    # Trigger run 2 -> 202
    res2 = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"order_id": "ORD-2", "amount": 20}},
        headers=headers,
    )
    assert res2.status_code == 202

    # Trigger run 3 -> 429 CONCURRENCY_LIMIT
    res3 = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"order_id": "ORD-3", "amount": 30}},
        headers=headers,
    )
    assert res3.status_code == 429
    assert res3.json()["code"] == "CONCURRENCY_LIMIT"


@pytest.mark.asyncio
async def test_cross_tenant_run_isolation(client: AsyncClient) -> None:
    """P4-T12: Cross-tenant GET /v1/runs/{id} and /v1/runs/{id}/steps return 404."""
    # Org A
    headers_a, org_a, wf_a = await setup_org_and_published_workflow(client, "org_a@example.com")
    res_run = await client.post(
        f"/v1/workflows/{wf_a}/runs",
        json={"inputs": {"order_id": "ORD-A", "amount": 100}},
        headers=headers_a,
    )
    run_id = res_run.json()["run_id"]

    # Org B user
    token_b = await get_auth_token(client, "org_b@example.com")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    await client.post("/v1/organizations", json={"name": "Org B"}, headers=headers_b)

    # User B accessing Org A run -> 404
    detail_res = await client.get(f"/v1/runs/{run_id}", headers=headers_b)
    assert detail_res.status_code == 404

    steps_res = await client.get(f"/v1/runs/{run_id}/steps", headers=headers_b)
    assert steps_res.status_code == 404

    # User A accessing Org A run -> 200
    detail_ok = await client.get(f"/v1/runs/{run_id}", headers=headers_a)
    assert detail_ok.status_code == 200
    assert detail_ok.json()["id"] == run_id
