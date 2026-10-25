"""Unit tests for RequestIdMiddleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_generated_request_id_in_response_and_errors(client: AsyncClient) -> None:
    """P1-T04: No header -> response has a UUID request id; same id appears in an error body."""
    response = await client.get("/non-existent-route")
    assert response.status_code == 404
    req_id = response.headers.get("x-request-id")
    assert req_id is not None
    assert len(req_id) >= 8

    data = response.json()
    assert data["request_id"] == req_id


@pytest.mark.asyncio
async def test_echo_valid_client_request_id(client: AsyncClient) -> None:
    """P1-T05: Valid client id echoed; invalid id replaced."""
    valid_id = "client-trace-12345"
    response = await client.get("/health", headers={"X-Request-ID": valid_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == valid_id

    # Invalid ID: too short (< 8 chars)
    resp_short = await client.get("/health", headers={"X-Request-ID": "short"})
    assert resp_short.status_code == 200
    assert resp_short.headers.get("x-request-id") != "short"

    # Invalid ID: illegal characters (spaces)
    resp_spaces = await client.get("/health", headers={"X-Request-ID": "invalid id with spaces"})
    assert resp_spaces.status_code == 200
    assert resp_spaces.headers.get("x-request-id") != "invalid id with spaces"

    # Invalid ID: too long (> 64 chars)
    too_long = "a" * 65
    resp_long = await client.get("/health", headers={"X-Request-ID": too_long})
    assert resp_long.status_code == 200
    assert resp_long.headers.get("x-request-id") != too_long
