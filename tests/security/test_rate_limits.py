"""Rate limiting tests (P9-T07)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.rate_limit import clear_rate_limits
from app.infrastructure.db.session import get_session
from app.main import create_app


@pytest.fixture
def rate_limit_app(integration_settings: Settings, db_engine: AsyncEngine):
    """Create test app with rate limiting enabled."""
    settings = integration_settings.model_copy(update={"rate_limit_enabled": True})
    application = create_app(settings)

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
    application.dependency_overrides.clear()


@pytest.fixture
async def rate_limit_client(rate_limit_app) -> AsyncIterator[AsyncClient]:
    """Test client bound to app with rate limiting enabled."""
    transport = ASGITransport(app=rate_limit_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.mark.asyncio
async def test_p9_t07_login_rate_limiting(rate_limit_client: AsyncClient) -> None:
    """P9-T07: 11th login attempt within 1 minute returns 429 RATE_LIMITED with Retry-After header."""
    clear_rate_limits()

    email = "ratelimit_target@example.com"
    payload = {"email": email, "password": "WrongPassword123!"}

    # 10 attempts should pass through (returning 401 INVALID_CREDENTIALS)
    for _ in range(10):
        resp = await rate_limit_client.post("/v1/auth/login", json=payload)
        assert resp.status_code == 401
        assert resp.json()["code"] == "INVALID_CREDENTIALS"

    # 11th attempt within the same minute should be rejected with 429 RATE_LIMITED
    resp_11 = await rate_limit_client.post("/v1/auth/login", json=payload)
    assert resp_11.status_code == 429
    assert resp_11.json()["code"] == "RATE_LIMITED"
    assert "Retry-After" in resp_11.headers
    retry_after = int(resp_11.headers["Retry-After"])
    assert 1 <= retry_after <= 60

    clear_rate_limits()


@pytest.mark.asyncio
async def test_different_email_not_blocked(rate_limit_client: AsyncClient) -> None:
    """Verify rate limits are per (IP, email) pair for login."""
    clear_rate_limits()

    # 10 attempts for user A
    for _ in range(10):
        await rate_limit_client.post(
            "/v1/auth/login",
            json={"email": "user_a@example.com", "password": "WrongPassword123!"},
        )

    # User B from same client can still attempt
    resp_b = await rate_limit_client.post(
        "/v1/auth/login",
        json={"email": "user_b@example.com", "password": "WrongPassword123!"},
    )
    assert resp_b.status_code == 401
    assert resp_b.json()["code"] == "INVALID_CREDENTIALS"

    clear_rate_limits()
