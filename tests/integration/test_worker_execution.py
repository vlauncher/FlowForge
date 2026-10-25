"""Integration tests for worker execution loop and step processing (P4-T09)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.executions.models import StepAttempt, WorkflowRun
from app.workers.runner import execute_run


async def get_auth_token(client: AsyncClient, email: str) -> str:
    signup_res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return signup_res.json()["access_token"]


def three_step_workflow() -> dict:
    return {
        "schema_version": 1,
        "name": "Three Step Branching Flow",
        "inputs_schema": {
            "type": "object",
            "required": ["val"],
            "properties": {"val": {"type": "integer"}},
        },
        "start": "step_init",
        "steps": [
            {
                "id": "step_init",
                "type": "set_data",
                "config": {"values": {"computed_num": "{{ inputs.val }}"}},
                "next": "step_check",
            },
            {
                "id": "step_check",
                "type": "condition",
                "config": {
                    "branches": [
                        {
                            "when": {
                                "op": "gt",
                                "left": "{{ steps.step_init.output.computed_num }}",
                                "right": 10,
                            },
                            "next": "step_high",
                        }
                    ],
                    "else": "step_low",
                },
            },
            {
                "id": "step_high",
                "type": "set_data",
                "config": {"values": {"result": "high_value"}},
                "next": None,
            },
            {
                "id": "step_low",
                "type": "set_data",
                "config": {"values": {"result": "low_value"}},
                "next": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_worker_executes_three_step_workflow(
    client: AsyncClient, db_engine: AsyncEngine
) -> None:
    """P4-T09: set_data -> condition -> set_data transitions QUEUED -> RUNNING -> SUCCEEDED with 3 step_attempts."""
    token = await get_auth_token(client, "worker_e2e@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Setup org & workflow
    org_res = await client.post(
        "/v1/organizations", json={"name": "Worker E2E Org"}, headers=headers
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Three Step Flow"},
        headers=headers,
    )
    wf_id = wf_res.json()["id"]

    # Draft & publish
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": three_step_workflow()},
        headers=headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)

    # Trigger run with val=25 (should take step_high branch)
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"val": 25}},
        headers=headers,
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["run_id"]

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # Execute run with worker
    await execute_run(run_id, session_factory=factory)

    # Verify run completed successfully
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        assert run.state == "SUCCEEDED"
        assert run.outputs == {"result": "high_value"}
        assert run.finished_at is not None
        assert run.lease_owner is None

        # Verify step attempts: step_init, step_check, step_high
        att_stmt = (
            select(StepAttempt)
            .where(StepAttempt.run_id == run_id)
            .order_by(StepAttempt.started_at.asc(), StepAttempt.attempt_no.asc())
        )
        att_res = await session.execute(att_stmt)
        attempts = list(att_res.scalars().all())

        assert len(attempts) == 3
        assert [a.step_id for a in attempts] == ["step_init", "step_check", "step_high"]
        assert all(a.status == "SUCCEEDED" for a in attempts)
        assert attempts[0].output == {"computed_num": 25}
        assert attempts[2].output == {"result": "high_value"}
