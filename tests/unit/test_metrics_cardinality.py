"""Unit tests enforcing low-cardinality label constraints on Prometheus metrics (P8-T02)."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.observability.metrics import REGISTRY

UUID_REGEX = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
FORBIDDEN_LABELS = {"run_id", "org_id", "user_id", "workflow_id", "request_id"}


def test_registered_metrics_label_names() -> None:
    """Enforce that no registered metric uses high-cardinality forbidden label names."""
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            for label_name in sample.labels:
                assert label_name not in FORBIDDEN_LABELS, (
                    f"Metric {sample.name} uses forbidden label '{label_name}'"
                )


@pytest.mark.asyncio
async def test_route_template_cardinality_no_uuid(
    client: AsyncClient,
) -> None:
    """P8-T02: Hitting /v1/runs/{uuid} produces route_template '/v1/runs/{run_id}' and never raw UUID."""
    fake_run_id = uuid4()
    # Hit an endpoint containing a UUID in the path
    res = await client.get(f"/v1/runs/{fake_run_id}")
    # Endpoint might return 401 or 404, which is expected
    assert res.status_code in (401, 404)

    # Scrape registry samples
    for metric in REGISTRY.collect():
        if metric.name in (
            "flowforge_http_requests_total",
            "flowforge_http_request_duration_seconds",
        ):
            for sample in metric.samples:
                route_val = sample.labels.get("route_template", "")
                if route_val:
                    # Assert no UUID is leaked inside route_template
                    assert not UUID_REGEX.search(route_val), (
                        f"Metric {sample.name} leaked raw UUID in route_template: {route_val}"
                    )
                    if f"/v1/runs/{fake_run_id}" in str(res.request.url):
                        # Verify normalized template is used
                        if "/runs/" in route_val:
                            assert "{" in route_val and "}" in route_val, (
                                f"Expected parameterized route template, got: {route_val}"
                            )
