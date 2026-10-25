"""Low-cardinality Prometheus metrics definitions and scrape handler (Phase 8)."""

from __future__ import annotations

import re
import time

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Dedicated registry for FlowForge
REGISTRY = CollectorRegistry(auto_describe=True)

# 1. HTTP metrics
HTTP_REQUESTS_TOTAL = Counter(
    "flowforge_http_requests_total",
    "Total HTTP requests handled by FlowForge API",
    ["method", "route_template", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "flowforge_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route_template"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

# 2. Worker & Execution metrics
RUNS_TOTAL = Counter(
    "flowforge_runs_total",
    "Total terminal workflow run transitions",
    ["state"],
    registry=REGISTRY,
)

STEP_ATTEMPTS_TOTAL = Counter(
    "flowforge_step_attempts_total",
    "Total step attempts executed across workflows",
    ["step_type", "status"],
    registry=REGISTRY,
)

# 3. AI & LLM metrics
LLM_REQUESTS_TOTAL = Counter(
    "flowforge_llm_requests_total",
    "Total LLM generation requests executed",
    ["provider", "model", "outcome"],
    registry=REGISTRY,
)

LLM_TOKENS_TOTAL = Counter(
    "flowforge_llm_tokens_total",
    "Total prompt and completion tokens consumed",
    ["provider", "model", "token_type"],
    registry=REGISTRY,
)

# 4. Live Queued & Outbox Gauges
OLDEST_QUEUED_RUN_AGE_SECONDS = Gauge(
    "flowforge_oldest_queued_run_age_seconds",
    "Age of the oldest workflow run currently in QUEUED state in seconds",
    registry=REGISTRY,
)

OUTBOX_UNPUBLISHED_COUNT = Gauge(
    "flowforge_outbox_unpublished_count",
    "Number of outbox events awaiting publication to message broker",
    registry=REGISTRY,
)


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Starlette middleware capturing HTTP request counters and duration histograms."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Don't meter the /metrics scrape endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        start_time = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = max(0.0, time.perf_counter() - start_time)
            method = request.method
            route = request.scope.get("route")
            route_template = (
                getattr(route, "path", None)
                or getattr(route, "path_format", None)
                or request.url.path
            )
            # Mask UUIDs to strictly enforce low cardinality
            route_template = re.sub(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                "{id}",
                route_template,
                flags=re.IGNORECASE,
            )

            # Safety check: route_template protected against high-cardinality
            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                route_template=route_template,
                status_code=str(status_code),
            ).inc()

            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method,
                route_template=route_template,
            ).observe(duration)


async def update_live_gauges(session: AsyncSession) -> None:
    """Query live PostgreSQL database state to update queue and outbox gauges."""
    # 1. Oldest queued run age
    q_res = await session.execute(
        text("""
            SELECT COALESCE(EXTRACT(EPOCH FROM (now() - MIN(created_at))), 0)
            FROM workflow_runs
            WHERE state = 'QUEUED'
        """)
    )
    oldest_age = float(q_res.scalar_one_or_none() or 0.0)
    OLDEST_QUEUED_RUN_AGE_SECONDS.set(max(0.0, oldest_age))

    # 2. Outbox unpublished count
    o_res = await session.execute(
        text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
    )
    unpub_count = int(o_res.scalar_one_or_none() or 0)
    OUTBOX_UNPUBLISHED_COUNT.set(unpub_count)


def get_metrics_content(registry: CollectorRegistry = REGISTRY) -> bytes:
    """Generate plaintext Prometheus metrics payload."""
    return generate_latest(registry)
