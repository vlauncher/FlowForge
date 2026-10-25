"""Unit tests for health and readiness endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.readiness import clear_checks, register_check


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok_with_request_id(client: AsyncClient) -> None:
    """P1-T01: GET /health -> 200 {"status":"ok"} with X-Request-ID header."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) >= 8


@pytest.mark.asyncio
async def test_ready_endpoint_with_no_checks(client: AsyncClient) -> None:
    """P1-T02: No checks registered, GET /ready -> 200 {"status":"ready","checks":{}}."""
    clear_checks()
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


@pytest.mark.asyncio
async def test_ready_endpoint_with_failing_check(client: AsyncClient) -> None:
    """P1-T03: A registered failing check -> GET /ready -> 503, code=SERVICE_UNAVAILABLE."""

    async def failing_db_check() -> None:
        raise ConnectionError("Database unreachable")

    async def ok_cache_check() -> None:
        return

    register_check("database", failing_db_check)
    register_check("cache", ok_cache_check)

    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"

    data = response.json()
    assert data["code"] == "SERVICE_UNAVAILABLE"
    assert data["status"] == 503
    assert "errors" in data
    checks_map = {item["check"]: item["status"] for item in data["errors"]}
    assert checks_map["database"] == "fail"
    assert checks_map["cache"] == "ok"
