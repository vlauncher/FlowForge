"""Integration tests for readiness probes, strict schema validation, and session isolation."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.readiness import clear_checks, register_check
from app.infrastructure.db.session import get_session
from app.main import check_db_readiness, create_app


@pytest.mark.asyncio
async def test_ready_endpoint_db_probe(client: AsyncClient, integration_settings: Settings) -> None:
    """P2-T24: /ready returns 200 with checks.db="ok"; with invalid DB URL returns 503."""
    clear_checks()
    register_check("db", check_db_readiness)

    # 1. Healthy database connection
    resp_ok = await client.get("/ready")
    assert resp_ok.status_code == 200
    assert resp_ok.json()["checks"]["db"] == "ok"

    # 2. Broken database connection returns 503 SERVICE_UNAVAILABLE
    broken_settings = integration_settings.model_copy(
        update={"database_url": "postgresql+asyncpg://invalid:invalid@localhost:9999/none"}
    )
    broken_app = create_app(broken_settings)
    clear_checks()

    async def broken_db_check() -> None:
        from sqlalchemy import text

        from app.infrastructure.db.session import get_engine, get_session_factory

        factory = get_session_factory(get_engine(broken_settings))
        async with factory() as session:
            await session.execute(text("SELECT 1"))

    register_check("db", broken_db_check)

    async with AsyncClient(
        transport=ASGITransport(app=broken_app, raise_app_exceptions=False), base_url="http://test"
    ) as broken_client:
        resp_fail = await broken_client.get("/ready")
        assert resp_fail.status_code == 503
        data = resp_fail.json()
        assert data["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_extra_fields_forbidden(client: AsyncClient) -> None:
    """P2-T28: Request bodies with unknown fields are rejected with 422 (extra='forbid')."""
    resp = await client.post(
        "/v1/auth/signup",
        json={
            "email": "hacker@example.com",
            "password": "Password123456!",
            "display_name": "Hacker",
            "admin": True,  # Unknown field
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_concurrent_requests_use_distinct_sessions(
    app, client: AsyncClient, db_engine: AsyncEngine
) -> None:
    """P2-T29: Concurrent requests receive isolated, distinct AsyncSession instances."""
    session_ids: list[int] = []
    lock = asyncio.Lock()
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def tracking_session_dep() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            async with lock:
                session_ids.append(id(session))
            yield session

    app.dependency_overrides[get_session] = tracking_session_dep

    req_a = client.post(
        "/v1/auth/signup",
        json={"email": "s1@example.com", "password": "Password123456!", "display_name": "S1"},
    )
    req_b = client.post(
        "/v1/auth/signup",
        json={"email": "s2@example.com", "password": "Password123456!", "display_name": "S2"},
    )
    res_a, res_b = await asyncio.gather(req_a, req_b)
    assert res_a.status_code == 201
    assert res_b.status_code == 201

    assert len(session_ids) == 2
    assert session_ids[0] != session_ids[1]


def test_static_tenant_parameter_check() -> None:
    """P2-T30: Execute scripts/check_tenant_params.py to enforce org_id parameter across repositories."""
    result = subprocess.run(
        [sys.executable, "scripts/check_tenant_params.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Static check failed:\n{result.stderr}\n{result.stdout}"
