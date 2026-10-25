"""Integration tests for the Prometheus metrics scrape endpoint (P8-T04)."""

from __future__ import annotations

import datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


async def signup_user(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_metrics_endpoint_reflects_live_db_state(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P8-T04: GET /metrics returns 200 with queue lag and unpublished count from DB."""
    owner_token = await signup_user(client, "metrics_user@example.com")

    # Create org
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Metrics Corp", "slug": "metrics-corp"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    # Create workflow
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Metrics Pipeline"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    wf_id = wf_res.json()["id"]

    # Version and publish
    definition = {
        "schema_version": 1,
        "name": "Metrics Pipeline",
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

    # Trigger run -> creates run in QUEUED and outbox in unpublished
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    run_id = UUID(run_res.json()["run_id"])

    # Age the queued run by 15s in the DB
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        past_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=15)
        await session.execute(
            text("UPDATE workflow_runs SET created_at = :past WHERE id = :run_id"),
            {"past": past_time, "run_id": run_id},
        )
        await session.commit()

    # Scrape /metrics endpoint
    res = await client.get("/metrics")
    assert res.status_code == 200
    body = res.text

    assert "flowforge_oldest_queued_run_age_seconds" in body
    assert "flowforge_outbox_unpublished_count" in body

    found_age = False
    found_unpub = False

    for line in body.splitlines():
        if line.startswith("flowforge_oldest_queued_run_age_seconds "):
            val = float(line.split()[1])
            assert val >= 10.0, f"Expected oldest queued run age >= 10s, got {val}"
            found_age = True
        elif line.startswith("flowforge_outbox_unpublished_count "):
            val = float(line.split()[1])
            assert val >= 1.0, f"Expected outbox unpublished count >= 1, got {val}"
            found_unpub = True

    assert found_age and found_unpub
