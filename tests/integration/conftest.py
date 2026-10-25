"""Integration test fixtures with PostgreSQL database truncation and fresh app instances."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.readiness import clear_checks
from app.infrastructure.db.session import get_session
from app.main import create_app

# Default to local container; can be overridden via TEST_DATABASE_URL
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge",
)


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    """Return Settings configured for integration tests."""
    return Settings(
        app_env="test",
        database_url=TEST_DB_URL,
        jwt_secret="integration-test-secret-key-at-least-32-chars-long!",
        jwt_issuer="flowforge",
        jwt_audience="flowforge-api",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=604800,
        api_cors_origins=["http://localhost:5173", "http://testserver:5173"],
        max_request_bytes=100_000,
        rate_limit_enabled=False,
    )


@pytest.fixture
async def db_engine(integration_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Provide a test-scoped AsyncEngine cleanly disposed on each test's event loop."""
    engine = create_async_engine(integration_settings.database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def truncate_tables(db_engine: AsyncEngine) -> AsyncIterator[None]:
    """Truncate all data tables before each test to ensure complete isolation."""
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE budget_reservations, triggers, audit_events, approval_requests, usage_records, tool_effects, integration_credentials, "
                "step_attempts, workflow_runs, outbox_events, "
                "workflow_versions, workflows, memberships, "
                "organizations, refresh_tokens, users RESTART IDENTITY CASCADE;"
            )
        )
    yield


@pytest.fixture
def app(integration_settings: Settings, db_engine: AsyncEngine):
    """Return a fresh FastAPI application instance for each integration test."""
    clear_checks()
    application = create_app(integration_settings)

    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_session] = override_get_session
    yield application
    clear_checks()
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """Provide an asynchronous HTTPX test client bound to the ASGI application."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Provide a direct database session for test state setup and verification."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session
