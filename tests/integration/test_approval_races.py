"""Integration tests for approval race conditions and cancellation (P7-T05, P7-T06, P7-T08)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.modules.approvals.models import ApprovalRequest
from app.modules.executions.models import WorkflowRun
from app.workers.runner import execute_run


async def signup_user(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return res.json()["access_token"]


def make_approval_workflow() -> dict:
    return {
        "schema_version": 1,
        "name": "Race Ticket Workflow",
        "inputs_schema": {
            "type": "object",
            "required": ["ticket_id"],
            "properties": {"ticket_id": {"type": "string"}},
        },
        "start": "triage_approval",
        "steps": [
            {
                "id": "triage_approval",
                "type": "approval",
                "config": {
                    "assigned_role": "reviewer",
                    "expires_in_seconds": 86400,
                    "summary": "Approve processing for ticket {{ inputs.ticket_id }}",
                },
                "next": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_concurrent_decisions_single_winner_race(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P7-T05: Two reviewers concurrently decide (approve & reject); exactly one 200, one 409."""
    owner_token = await signup_user(client, "race_owner@example.com")
    reviewer1_token = await signup_user(client, "reviewer_1@example.com")
    reviewer2_token = await signup_user(client, "reviewer_2@example.com")

    # Org setup
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Race Corp", "slug": "race-corp"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    # Add both reviewers
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "reviewer_1@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "reviewer_2@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # Workflow setup
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Race Pipeline"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    wf_id = wf_res.json()["id"]

    definition = make_approval_workflow()
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/workflows/{wf_id}/publish",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # Trigger run and pause at approval
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"ticket_id": "TCK-RACE-1"}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    run_id = UUID(run_res.json()["run_id"])

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory)

    # Fetch approval ID
    apps_res = await client.get(
        f"/v1/organizations/{org_id}/approvals",
        headers={"Authorization": f"Bearer {reviewer1_token}"},
    )
    approval_id = apps_res.json()["items"][0]["id"]

    # Concurrently fire approve and reject
    async def post_decision(token: str, decision: str):
        return await client.post(
            f"/v1/approvals/{approval_id}/decisions",
            json={"decision": decision, "comment": f"Decided {decision}"},
            headers={"Authorization": f"Bearer {token}"},
        )

    res1, res2 = await asyncio.gather(
        post_decision(reviewer1_token, "approve"),
        post_decision(reviewer2_token, "reject"),
    )

    statuses = {res1.status_code, res2.status_code}
    assert statuses == {200, 409}, (
        f"Expected {200, 409}, got {[res1.status_code, res2.status_code]}"
    )

    winner_res = res1 if res1.status_code == 200 else res2
    conflict_res = res2 if res1.status_code == 200 else res1

    assert conflict_res.json()["code"] == "INVALID_STATE_TRANSITION"

    # Verify final database state is consistent with the winner
    winning_state = winner_res.json()["state"]
    assert winning_state in ("APPROVED", "REJECTED")

    async with session_factory() as session:
        app_db = (
            await session.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == UUID(approval_id))
            )
        ).scalar_one()
        assert app_db.state == winning_state

        run_db = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        if winning_state == "APPROVED":
            assert run_db.state == "QUEUED"
        else:
            assert run_db.state == "FAILED"
            assert run_db.error_code == "APPROVAL_REJECTED"


@pytest.mark.asyncio
async def test_reviewer_demoted_before_deciding_returns_403(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P7-T06: Reviewer demoted to viewer before deciding gets 403 FORBIDDEN."""
    owner_token = await signup_user(client, "demote_owner@example.com")
    reviewer_token = await signup_user(client, "demoted_reviewer@example.com")

    # Org setup
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Demote Corp", "slug": "demote-corp"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    # Add reviewer member
    member_res = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "demoted_reviewer@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    user_id = member_res.json()["user_id"]

    # Workflow setup
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Demote Pipeline"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    wf_id = wf_res.json()["id"]

    definition = make_approval_workflow()
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/workflows/{wf_id}/publish",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # Trigger run and pause at approval
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"ticket_id": "TCK-DEMOTE-1"}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    run_id = UUID(run_res.json()["run_id"])

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory)

    # Reviewer fetches pending approval
    apps_res = await client.get(
        f"/v1/organizations/{org_id}/approvals",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert apps_res.status_code == 200
    approval_id = apps_res.json()["items"][0]["id"]

    # Admin demotes reviewer to viewer
    patch_res = await client.patch(
        f"/v1/organizations/{org_id}/members/{user_id}",
        json={"role": "viewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["role"] == "viewer"

    # Demoted user attempts to post decision
    decide_res = await client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"decision": "approve", "comment": "Trying anyway"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert decide_res.status_code == 403
    assert decide_res.json()["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_run_cancelled_marks_pending_approval_cancelled(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P7-T08: Cancelling a WAITING_APPROVAL run marks run and approval CANCELLED; subsequent POST returns 409."""
    owner_token = await signup_user(client, "cancel_owner@example.com")
    reviewer_token = await signup_user(client, "cancel_reviewer@example.com")

    # Org setup
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Cancel Corp", "slug": "cancel-corp"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    # Add reviewer
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "cancel_reviewer@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # Workflow setup
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Cancel Pipeline"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    wf_id = wf_res.json()["id"]

    definition = make_approval_workflow()
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/workflows/{wf_id}/publish",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # Trigger run and pause at approval
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"ticket_id": "TCK-CANCEL-1"}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    run_id = UUID(run_res.json()["run_id"])

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory)

    # Verify run is WAITING_APPROVAL
    async with session_factory() as session:
        r_db = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert r_db.state == "WAITING_APPROVAL"

        app_db = (
            await session.execute(select(ApprovalRequest).where(ApprovalRequest.run_id == run_id))
        ).scalar_one()
        assert app_db.state == "PENDING"
        approval_id = str(app_db.id)

    # Cancel the run via API
    cancel_res = await client.post(
        f"/v1/runs/{run_id}/cancel",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["state"] == "CANCELLED"

    # Verify DB state of approval request is CANCELLED
    async with session_factory() as session:
        app_after = (
            await session.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == UUID(approval_id))
            )
        ).scalar_one()
        assert app_after.state == "CANCELLED"

    # Attempt to decide on cancelled approval -> returns 409
    decide_res = await client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"decision": "approve", "comment": "Too late"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert decide_res.status_code == 409
    assert decide_res.json()["code"] == "INVALID_STATE_TRANSITION"
