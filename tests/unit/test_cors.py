"""Unit tests for CORS origin enforcement."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_cors_preflight_allowed_origin(client: AsyncClient) -> None:
    """P1-T10: Origin http://localhost:5173 preflight -> allowed with credentials header."""
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "X-Request-ID, Content-Type",
    }
    response = await client.options("/health", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_cors_disallowed_origin(client: AsyncClient) -> None:
    """P1-T10: Origin http://evil.example -> no access-control-allow-origin."""
    headers = {
        "Origin": "http://evil.example",
        "Access-Control-Request-Method": "GET",
    }
    response = await client.options("/health", headers=headers)
    assert "access-control-allow-origin" not in response.headers
