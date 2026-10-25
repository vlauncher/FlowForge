"""Unit tests for Problem Details error handlers and dependency isolation."""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from httpx import AsyncClient
from pydantic import BaseModel

from app.core.config import Settings, get_settings


class EchoInput(BaseModel):
    name: str
    count: int


dummy_router = APIRouter()


@dummy_router.post("/test-validation")
async def validation_route(payload: EchoInput) -> dict[str, str]:
    return {"status": "ok"}


@dummy_router.get("/test-unhandled-error")
async def unhandled_error_route() -> None:
    raise RuntimeError("secret-database-token-xyz")


@pytest.mark.asyncio
async def test_unknown_route_returns_404_problem_details(client: AsyncClient) -> None:
    """P1-T06: Unknown route -> 404 NOT_FOUND, no traceback or internal paths in body."""
    response = await client.get("/v1/non-existent-resource")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"

    data = response.json()
    assert data["code"] == "NOT_FOUND"
    assert data["status"] == 404
    assert data["title"] == "Not Found"
    assert "traceback" not in data
    assert 'File "' not in data.get("detail", "")


@pytest.mark.asyncio
async def test_method_not_allowed_returns_405(client: AsyncClient) -> None:
    """P1-T07: Wrong method on /health -> 405 METHOD_NOT_ALLOWED."""
    response = await client.post("/health")
    assert response.status_code == 405
    assert response.headers["content-type"] == "application/problem+json"

    data = response.json()
    assert data["code"] == "METHOD_NOT_ALLOWED"
    assert data["status"] == 405


@pytest.mark.asyncio
async def test_validation_and_malformed_json_errors(app, client: AsyncClient) -> None:
    """P1-T08: Invalid body -> 422 VALIDATION_ERROR; malformed JSON -> 400 BAD_REQUEST."""
    app.include_router(dummy_router)

    # Malformed JSON
    resp_malformed = await client.post(
        "/test-validation",
        content='{"name": "test", invalid_json',
        headers={"Content-Type": "application/json"},
    )
    assert resp_malformed.status_code == 400
    data_bad = resp_malformed.json()
    assert data_bad["code"] == "BAD_REQUEST"

    # Schema invalid (missing 'count', 'name' wrong type)
    resp_invalid = await client.post(
        "/test-validation",
        json={"name": 12345},
    )
    assert resp_invalid.status_code == 422
    data_val = resp_invalid.json()
    assert data_val["code"] == "VALIDATION_ERROR"
    assert "errors" in data_val
    fields = [err["field"] for err in data_val["errors"]]
    assert "count" in fields


@pytest.mark.asyncio
async def test_unhandled_exception_sanitizes_stack_trace(app, client: AsyncClient) -> None:
    """P1-T09: Raising RuntimeError("secret-xyz") -> 500 INTERNAL_ERROR, secrets omitted."""
    app.include_router(dummy_router)

    response = await client.get("/test-unhandled-error")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"

    data = response.json()
    assert data["code"] == "INTERNAL_ERROR"
    assert "secret-database-token-xyz" not in str(data)
    assert data["detail"] == "An unexpected error occurred."
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_dependency_override_isolation_step_one(app, client: AsyncClient) -> None:
    """P1-T16 part 1: Override settings in one test."""
    custom_settings = Settings(app_env="prod", max_request_bytes=42)
    app.dependency_overrides[get_settings] = lambda: custom_settings

    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dependency_override_isolation_step_two(app, client: AsyncClient) -> None:
    """P1-T16 part 2: Verify override did not leak into the subsequent test."""
    assert get_settings not in app.dependency_overrides
