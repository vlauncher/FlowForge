"""Shared pytest configuration and test fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

os.environ["APP_ENV"] = "test"

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.readiness import clear_checks
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    """Return isolated test settings."""
    return Settings(
        app_env="test",
        log_level="DEBUG",
        api_cors_origins=["http://localhost:5173", "http://testserver:5173"],
        max_request_bytes=100_000,
    )


@pytest.fixture
def app(test_settings: Settings):
    """Return a fresh FastAPI application instance for each test."""
    clear_checks()
    application = create_app(test_settings)
    yield application
    clear_checks()
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """Provide an asynchronous HTTPX test client bound to the ASGI app."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
