"""Integration tests for the organization usage and cost reporting API (P8-T05)."""

from __future__ import annotations

import datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.usage.models import UsageRecord


async def signup_user(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_usage_api_aggregation_and_role_security(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P8-T05: GET /v1/organizations/{org_id}/usage aggregates metrics; reviewer gets 403, stranger gets 404."""
    owner_token = await signup_user(client, "usage_owner@example.com")
    reviewer_token = await signup_user(client, "usage_reviewer@example.com")
    stranger_token = await signup_user(client, "usage_stranger@example.com")

    # 1. Create org
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Usage Corp", "slug": "usage-corp"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    # 2. Add reviewer member
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "usage_reviewer@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # 3. Setup workflow and run
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Usage Pipeline"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    wf_id = wf_res.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Usage Pipeline",
        "inputs_schema": {"type": "object"},
        "start": "step_1",
        "steps": [
            {
                "id": "step_1",
                "type": "set_data",
                "config": {"values": {"ok": True}},
                "next": None,
            }
        ],
    }
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/workflows/{wf_id}/publish",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    run_id = UUID(run_res.json()["run_id"])

    # 4. Insert sample UsageRecord rows
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    now = datetime.datetime.now(datetime.UTC)

    async with session_factory() as session:
        rec1 = UsageRecord(
            org_id=UUID(org_id),
            run_id=run_id,
            step_id="classify_step",
            attempt_id=None,
            provider="openrouter",
            model_name="openrouter/free",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            estimated_cost_micro_usd=240,
            billed_cost_micro_usd=0,
            latency_ms=150,
            prompt_template_id="ticket_classify",
            prompt_template_version=1,
            outcome="ok",
            created_at=now,
        )
        rec2 = UsageRecord(
            org_id=UUID(org_id),
            run_id=run_id,
            step_id="transform_step",
            attempt_id=None,
            provider="openrouter",
            model_name="openrouter/free",
            prompt_tokens=200,
            completion_tokens=40,
            total_tokens=240,
            estimated_cost_micro_usd=480,
            billed_cost_micro_usd=0,
            latency_ms=180,
            prompt_template_id="ticket_transform",
            prompt_template_version=1,
            outcome="ok",
            created_at=now,
        )
        session.add_all([rec1, rec2])
        await session.commit()

    # 5. Owner queries usage -> 200 OK with aggregated totals
    usage_res = await client.get(
        f"/v1/organizations/{org_id}/usage",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert usage_res.status_code == 200
    data = usage_res.json()

    assert data["org_id"] == org_id
    assert data["totals"]["llm_calls"] == 2
    assert data["totals"]["prompt_tokens"] == 300
    assert data["totals"]["completion_tokens"] == 60
    assert data["totals"]["total_tokens"] == 360
    assert data["totals"]["estimated_cost_micro_usd"] == 720
    assert len(data["by_model"]) == 1
    assert data["by_model"][0]["model_name"] == "openrouter/free"
    assert data["by_model"][0]["calls"] == 2

    # Verify run counts
    assert data["runs_by_state"]["QUEUED"] >= 1

    # 6. Reviewer queries -> 403 Forbidden (reviewer lacks USAGE_READ)
    reviewer_res = await client.get(
        f"/v1/organizations/{org_id}/usage",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert reviewer_res.status_code == 403

    # 7. Stranger (non-member) queries -> 404 Not Found
    stranger_res = await client.get(
        f"/v1/organizations/{org_id}/usage",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert stranger_res.status_code == 404
