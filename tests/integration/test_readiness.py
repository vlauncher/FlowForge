"""Integration test for readiness probe checking both DB and RabbitMQ broker (P4-S06)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.readiness import clear_checks, register_check
from app.main import check_broker_readiness, check_db_readiness


@pytest.mark.asyncio
async def test_ready_endpoint_checks_db_and_broker(client: AsyncClient) -> None:
    clear_checks()
    register_check("db", check_db_readiness)
    register_check("broker", check_broker_readiness)

    res = await client.get("/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["checks"]["db"] == "ok"
    assert data["checks"]["broker"] == "ok"
