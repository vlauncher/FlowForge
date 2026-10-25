"""Integration tests for end-to-end distributed trace propagation (P8-T03)."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.infrastructure.messaging.outbox_publisher import publish_batch
from app.observability.tracing import setup_tracing
from app.workers.runner import execute_run


async def signup_user(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return res.json()["access_token"]


def make_three_step_workflow() -> dict:
    return {
        "schema_version": 1,
        "name": "Tracing Pipeline",
        "inputs_schema": {
            "type": "object",
            "required": ["val"],
            "properties": {"val": {"type": "integer"}},
        },
        "start": "step_a",
        "steps": [
            {
                "id": "step_a",
                "type": "set_data",
                "config": {"values": {"computed_a": "{{ inputs.val }}"}},
                "next": "step_b",
            },
            {
                "id": "step_b",
                "type": "set_data",
                "config": {"values": {"computed_b": 42}},
                "next": "step_c",
            },
            {
                "id": "step_c",
                "type": "set_data",
                "config": {"values": {"computed_c": "done"}},
                "next": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_end_to_end_trace_propagation(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P8-T03: api.trigger_run -> outbox.publish -> worker.execute_run -> step.* share trace_id."""
    exporter = InMemorySpanExporter()
    setup_tracing(service_name="flowforge-test", exporter=exporter)

    owner_token = await signup_user(client, "tracing_owner@example.com")

    # 1. Setup organization and workflow
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Trace Corp", "slug": "trace-corp"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Trace Pipeline"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    wf_id = wf_res.json()["id"]

    definition = make_three_step_workflow()
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": definition},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/workflows/{wf_id}/publish",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # 2. Trigger run (spans api.trigger_run)
    run_res = await client.post(
        f"/v1/workflows/{wf_id}/runs",
        json={"inputs": {"val": 100}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert run_res.status_code == 202
    run_id = UUID(run_res.json()["run_id"])

    # 3. Publish outbox (spans outbox.publish)
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    published = await publish_batch(
        session_factory=session_factory,
        broker_publish=lambda ev: None,
    )
    assert published >= 1

    # 4. Execute 3-step run (spans worker.execute_run and worker.step.*)
    await execute_run(run_id, session_factory=session_factory)

    # 5. Verify exported spans
    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]

    assert "api.trigger_run" in span_names
    assert "outbox.publish" in span_names
    assert "worker.execute_run" in span_names
    assert "worker.step.set_data" in span_names

    trigger_span = next(s for s in spans if s.name == "api.trigger_run")
    outbox_span = next(s for s in spans if s.name == "outbox.publish")
    worker_span = next(s for s in spans if s.name == "worker.execute_run")
    step_spans = [s for s in spans if s.name == "worker.step.set_data"]

    root_trace_id = trigger_span.context.trace_id

    # Trace ID propagation check: All spans share the same root trace_id
    assert outbox_span.context.trace_id == root_trace_id
    assert worker_span.context.trace_id == root_trace_id
    for step_s in step_spans:
        assert step_s.context.trace_id == root_trace_id

    # Parent-child relationship checks
    assert outbox_span.parent.span_id == trigger_span.context.span_id
    assert worker_span.parent.span_id == trigger_span.context.span_id
    for step_s in step_spans:
        assert step_s.parent.span_id == worker_span.context.span_id

    # Security check: verify no secrets or prompt bodies leaked into span attributes
    for s in spans:
        for attr_k, _attr_v in s.attributes.items():
            k_lower = attr_k.lower()
            assert "password" not in k_lower
            assert "secret" not in k_lower
            assert "authorization" not in k_lower
