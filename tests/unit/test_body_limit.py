"""Unit tests for BodySizeLimitMiddleware."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from httpx import AsyncClient

test_router = APIRouter()


@test_router.post("/echo")
async def echo_body(data: dict[str, str]) -> dict[str, str]:
    return data


@pytest.mark.asyncio
async def test_body_limit_enforcement(app, client: AsyncClient) -> None:
    """P1-T12: Content-Length above limit -> 413; body under limit passes."""
    app.include_router(test_router)

    # Payload within limit (test_settings max_request_bytes is 100_000)
    small_payload = {"msg": "hello world"}
    resp_ok = await client.post("/echo", json=small_payload)
    assert resp_ok.status_code == 200
    assert resp_ok.json() == small_payload

    # Payload declared or sent exceeding limit
    large_payload = {"msg": "x" * 150_000}
    resp_large = await client.post("/echo", json=large_payload)
    assert resp_large.status_code == 413
    assert resp_large.headers["content-type"] == "application/problem+json"

    data = resp_large.json()
    assert data["code"] == "PAYLOAD_TOO_LARGE"
    assert data["status"] == 413
