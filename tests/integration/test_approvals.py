"""Integration tests for approval steps, decisions, and expiry (P7-T02..P7-T04, P7-T07)."""

from __future__ import annotations

import datetime
from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import get_settings
from app.modules.approvals.models import ApprovalRequest
from app.modules.executions.models import StepAttempt, WorkflowRun
from app.workers.runner import execute_run
from app.workers.sweeper import sweep_expired_approvals


async def signup_user(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return res.json()["access_token"]


def make_approval_workflow() -> dict:
    return {
        "schema_version": 1,
        "name": "Support Ticket Approval Workflow",
        "inputs_schema": {
            "type": "object",
            "required": ["ticket_id", "body"],
            "properties": {"ticket_id": {"type": "string"}, "body": {"type": "string"}},
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
                "next": "crm_call",
            },
            {
                "id": "crm_call",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://api.crm.example.com/tickets",
                    "body": {"ticket_id": "{{ inputs.ticket_id }}"},
                    "effect": "read",
                },
                "next": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_workflow_pauses_at_approval_step(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P7-T02: Support-ticket workflow pauses at approve step: run state is WAITING_APPROVAL, lease cleared."""
    owner_token = await signup_user(client, "owner_t2@example.com")
    auth_headers = {"Authorization": f"Bearer {owner_token}"}

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Approval Corp", "slug": "approval-corp-1"},
        headers=auth_headers,
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Pipeline"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    definition = make_approval_workflow()
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=auth_headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=auth_headers)

    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"ticket_id": "TCK-555", "body": "Need refunds"}},
        headers=auth_headers,
    )
    assert run_res.status_code == 202
    run_id = UUID(run_res.json()["run_id"])

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory)

    # Verify run state is WAITING_APPROVAL and lease is cleared
    async with session_factory() as session:
        run_row = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert run_row.state == "WAITING_APPROVAL"
        assert run_row.lease_owner is None
        assert run_row.lease_expires_at is None
        assert run_row.current_step_id == "triage_approval"

        # Verify pending approval request created
        app_res = await session.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.run_id == run_id,
                ApprovalRequest.step_id == "triage_approval",
            )
        )
        app_row = app_res.scalar_one()
        assert app_row.state == "PENDING"
        assert app_row.assigned_role == "reviewer"
        assert app_row.summary == {"summary": "Approve processing for ticket TCK-555"}


@pytest.mark.asyncio
async def test_approval_decision_approve_resumes_and_completes_run(
    client: AsyncClient,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P7-T03: Approving transitions approval to APPROVED, run to QUEUED, worker completes SUCCEEDED."""
    monkeypatch.setattr(get_settings(), "egress_allowed_hosts", ["api.crm.example.com"])
    owner_token = await signup_user(client, "owner_t3@example.com")
    reviewer_token = await signup_user(client, "reviewer_t3@example.com")

    # 1. Setup org
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Approval Corp 3", "slug": "approval-corp-3"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    # 2. Add reviewer member
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "reviewer_t3@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # 3. Setup workflow
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Pipeline 3"},
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

    # 4. Trigger run and execute to pause
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"ticket_id": "TCK-777", "body": "Upgrade please"}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    run_id = UUID(run_res.json()["run_id"])

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory)

    # 5. Fetch approval
    apps_res = await client.get(
        f"/v1/organizations/{org_id}/approvals",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert apps_res.status_code == 200
    approval_list = apps_res.json()["items"]
    assert len(approval_list) == 1
    approval_id = approval_list[0]["id"]

    # 6. Reviewer decides: approve
    decide_res = await client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"decision": "approve", "comment": "Verified and approved ticket."},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert decide_res.status_code == 200
    assert decide_res.json()["state"] == "APPROVED"
    assert decide_res.json()["decision_comment"] == "Verified and approved ticket."

    # Verify run transitioned to QUEUED
    async with session_factory() as session:
        r_chk = (
            await session.execute(select(WorkflowRun.state).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert r_chk == "QUEUED"

    # 7. Worker resumes and finishes run
    mock_crm_called = False

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal mock_crm_called
        mock_crm_called = True
        return httpx.Response(200, json={"status": "ticket_created"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        await execute_run(run_id, session_factory=session_factory, http_client=mock_http)

    assert mock_crm_called is True

    async with session_factory() as session:
        final_run = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert final_run.state == "SUCCEEDED"
        assert final_run.context["triage_approval"]["decision"] == "approved"


@pytest.mark.asyncio
async def test_approval_decision_reject_fails_run_and_skips_crm(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P7-T04: Rejecting transitions approval to REJECTED and run to FAILED; downstream CRM never called."""
    owner_token = await signup_user(client, "owner_t4@example.com")
    reviewer_token = await signup_user(client, "reviewer_t4@example.com")

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Approval Corp 4", "slug": "approval-corp-4"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "reviewer_t4@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Pipeline 4"},
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

    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"ticket_id": "TCK-888", "body": "Invalid body"}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    run_id = UUID(run_res.json()["run_id"])

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory)

    apps_res = await client.get(
        f"/v1/organizations/{org_id}/approvals",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    approval_id = apps_res.json()["items"][0]["id"]

    # Reject
    decide_res = await client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"decision": "reject", "comment": "Spam ticket rejected."},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert decide_res.status_code == 200
    assert decide_res.json()["state"] == "REJECTED"

    # Verify run is FAILED with APPROVAL_REJECTED
    async with session_factory() as session:
        run_row = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert run_row.state == "FAILED"
        assert run_row.error_code == "APPROVAL_REJECTED"

        # Downstream crm_call attempt never created!
        crm_att = (
            await session.execute(
                select(StepAttempt).where(
                    StepAttempt.run_id == run_id,
                    StepAttempt.step_id == "crm_call",
                )
            )
        ).scalar_one_or_none()
        assert crm_att is None


@pytest.mark.asyncio
async def test_expired_approval_sweeper_marks_expired_and_fails_run(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P7-T07: Expired approval rejects decisions with 409 and sweeper transitions to EXPIRED/FAILED."""
    owner_token = await signup_user(client, "owner_t7@example.com")
    auth_headers = {"Authorization": f"Bearer {owner_token}"}

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Approval Corp 7", "slug": "approval-corp-7"},
        headers=auth_headers,
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Pipeline 7"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    definition = make_approval_workflow()
    # Set expiration to 60s
    definition["steps"][0]["config"]["expires_in_seconds"] = 60

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=auth_headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=auth_headers)

    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"ticket_id": "TCK-999", "body": "Timeout ticket"}},
        headers=auth_headers,
    )
    run_id = UUID(run_res.json()["run_id"])

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory)

    apps_res = await client.get(
        f"/v1/organizations/{org_id}/approvals",
        headers=auth_headers,
    )
    approval_id = apps_res.json()["items"][0]["id"]

    # Artificially age the expires_at timestamp to simulate expiration
    async with session_factory() as session:
        async with session.begin():
            app_obj = (
                await session.execute(
                    select(ApprovalRequest).where(ApprovalRequest.id == UUID(approval_id))
                )
            ).scalar_one()
            app_obj.expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
                seconds=10
            )

    # 1. Run the sweeper to expire the approval and transition the run
    swept = await sweep_expired_approvals(session_factory)
    assert swept >= 1

    async with session_factory() as session:
        run_row = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert run_row.state == "FAILED"
        assert run_row.error_code == "APPROVAL_EXPIRED"

        app_row = (
            await session.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == UUID(approval_id))
            )
        ).scalar_one()
        assert app_row.state == "EXPIRED"

    # 2. Subsequent attempt to decide must return 409 INVALID_STATE_TRANSITION
    decide_res = await client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"decision": "approve"},
        headers=auth_headers,
    )
    assert decide_res.status_code == 409
    assert decide_res.json()["code"] == "INVALID_STATE_TRANSITION"
