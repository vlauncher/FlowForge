"""Integration tests for AI workflow steps, structured output, and usage recording (P6-T06..P6-T08)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.ai.fake_client import FakeLLM
from app.modules.executions.models import WorkflowRun
from app.modules.usage.models import UsageRecord
from app.workers.runner import execute_run


async def get_auth_token(client: AsyncClient, email: str) -> str:
    signup_res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return signup_res.json()["access_token"]


@pytest.mark.asyncio
async def test_ai_classify_workflow_success_and_usage_record(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P6-T06: llm_classify -> condition -> set_data with FakeLLM succeeds and writes usage_records."""
    token = await get_auth_token(client, "alice_ai@example.com")
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 1. Create org
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "AI Classify Corp", "slug": "ai-classify-corp"},
        headers=auth_headers,
    )
    org_id = org_res.json()["id"]

    # 2. Create workflow
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Ticket Triage Workflow"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    # 3. Create draft version
    definition = {
        "schema_version": 1,
        "name": "Ticket Triage",
        "inputs_schema": {
            "type": "object",
            "required": ["ticket_id", "body"],
            "properties": {"ticket_id": {"type": "string"}, "body": {"type": "string"}},
        },
        "start": "classify_step",
        "steps": [
            {
                "id": "classify_step",
                "type": "llm_classify",
                "config": {
                    "prompt_template_id": "ticket_classify",
                    "input": "{{ inputs.body }}",
                    "labels": ["billing", "bug", "feature", "other"],
                    "max_tokens": 100,
                },
                "next": "route_step",
            },
            {
                "id": "route_step",
                "type": "condition",
                "config": {
                    "branches": [
                        {
                            "when": {
                                "op": "eq",
                                "left": "{{ steps.classify_step.output.label }}",
                                "right": "billing",
                            },
                            "next": "billing_handler",
                        }
                    ],
                    "else": "other_handler",
                },
            },
            {
                "id": "billing_handler",
                "type": "set_data",
                "config": {
                    "values": {
                        "category": "{{ steps.classify_step.output.label }}",
                        "status": "routed_to_finance",
                    }
                },
                "next": None,
            },
            {
                "id": "other_handler",
                "type": "set_data",
                "config": {"values": {"status": "routed_to_support"}},
                "next": None,
            },
        ],
    }

    ver_res = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=auth_headers,
    )
    assert ver_res.status_code == 201

    # 4. Publish version
    pub_res = await client.post(f"/v1/workflows/{wf_id}/publish", headers=auth_headers)
    assert pub_res.status_code == 200

    # 5. Trigger run
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={
            "inputs": {
                "ticket_id": "TCK-1001",
                "body": "I was charged twice on my monthly credit card bill.",
            }
        },
        headers=auth_headers,
    )
    assert run_res.status_code == 202
    run_id = uuid.UUID(run_res.json()["run_id"])

    # 6. Configure FakeLLM to classify as billing
    fake_llm = FakeLLM()
    fake_llm.queue_response({"label": "billing", "confidence": 0.96})

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory, llm_client=fake_llm)

    # 7. Verify run reached SUCCEEDED
    async with session_factory() as session:
        run_row = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert run_row.state == "SUCCEEDED"
        assert run_row.context["classify_step"] == {"label": "billing", "confidence": 0.96}
        assert run_row.outputs == {"category": "billing", "status": "routed_to_finance"}

        # Verify usage_record
        usage_res = await session.execute(
            select(UsageRecord).where(
                UsageRecord.run_id == run_id,
                UsageRecord.step_id == "classify_step",
            )
        )
        usage = usage_res.scalar_one()
        assert usage.outcome == "ok"
        assert usage.model_name == "openrouter/free"
        assert usage.prompt_tokens > 0
        assert usage.completion_tokens > 0
        assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
        assert usage.estimated_cost_micro_usd > 0
        assert usage.billed_cost_micro_usd == 0
        assert usage.prompt_template_id == "ticket_classify"
        assert usage.prompt_template_version >= 1


@pytest.mark.asyncio
async def test_ai_classify_fails_on_unlisted_label_after_retry(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P6-T07: FakeLLM returning unlisted label 'hacked' fails after 2 attempts with LLM_INVALID_OUTPUT."""
    token = await get_auth_token(client, "bob_ai@example.com")
    auth_headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Adversarial Corp", "slug": "adversarial-corp"},
        headers=auth_headers,
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Strict Label Flow"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Strict Classification",
        "inputs_schema": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        "start": "classify",
        "steps": [
            {
                "id": "classify",
                "type": "llm_classify",
                "config": {
                    "prompt_template_id": "ticket_classify",
                    "input": "{{ inputs.text }}",
                    "labels": ["sales", "support"],
                    "max_tokens": 100,
                },
                "next": None,
            }
        ],
    }

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=auth_headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=auth_headers)

    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"text": "Hello there"}},
        headers=auth_headers,
    )
    run_id = uuid.UUID(run_res.json()["run_id"])

    # Configure FakeLLM to return unlisted label on both attempts
    fake_llm = FakeLLM()
    fake_llm.queue_response({"label": "hacked", "confidence": 0.99})
    fake_llm.queue_response({"label": "hacked_again", "confidence": 0.99})

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory, llm_client=fake_llm)

    async with session_factory() as session:
        run_row = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert run_row.state == "FAILED"
        assert run_row.error_code == "LLM_INVALID_OUTPUT"
        # Context must remain clean: no invalid output stored!
        assert "classify" not in run_row.context

        # Verify 2 usage records recorded with outcome='invalid_output'
        usage_rows = (
            (
                await session.execute(
                    select(UsageRecord)
                    .where(UsageRecord.run_id == run_id)
                    .order_by(UsageRecord.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(usage_rows) == 2
        for u in usage_rows:
            assert u.outcome == "invalid_output"


@pytest.mark.asyncio
async def test_llm_transform_step_extracts_schema(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P6-T08: llm_transform step extracts structured data according to output_schema."""
    token = await get_auth_token(client, "carol_ai@example.com")
    auth_headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Transform Corp", "slug": "transform-corp"},
        headers=auth_headers,
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Lead Extraction"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Extract Contact Info",
        "inputs_schema": {
            "type": "object",
            "required": ["email_text"],
            "properties": {"email_text": {"type": "string"}},
        },
        "start": "extract_contact",
        "steps": [
            {
                "id": "extract_contact",
                "type": "llm_transform",
                "config": {
                    "prompt_template_id": "ticket_transform",
                    "input": "{{ inputs.email_text }}",
                    "output_schema": {
                        "type": "object",
                        "required": ["name", "email", "company"],
                        "properties": {
                            "name": {"type": "string"},
                            "email": {"type": "string"},
                            "company": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "max_tokens": 300,
                },
                "next": "finish",
            },
            {
                "id": "finish",
                "type": "set_data",
                "config": {
                    "values": {
                        "lead_name": "{{ steps.extract_contact.output.name }}",
                        "lead_email": "{{ steps.extract_contact.output.email }}",
                    }
                },
                "next": None,
            },
        ],
    }

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers=auth_headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", headers=auth_headers)

    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={
            "inputs": {"email_text": "Hi, I am John Doe from Acme Inc. Reach me at john@acme.com"}
        },
        headers=auth_headers,
    )
    run_id = uuid.UUID(run_res.json()["run_id"])

    fake_llm = FakeLLM()
    fake_llm.queue_response(
        {
            "name": "John Doe",
            "email": "john@acme.com",
            "company": "Acme Inc",
        }
    )

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await execute_run(run_id, session_factory=session_factory, llm_client=fake_llm)

    async with session_factory() as session:
        run_row = (
            await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))
        ).scalar_one()
        assert run_row.state == "SUCCEEDED"
        assert run_row.context["extract_contact"]["name"] == "John Doe"
        assert run_row.context["extract_contact"]["email"] == "john@acme.com"
        assert run_row.outputs == {"lead_name": "John Doe", "lead_email": "john@acme.com"}
