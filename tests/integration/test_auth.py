"""Integration tests for user authentication and session management (P2-T02 to P2-T07)."""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import Settings


@pytest.mark.asyncio
async def test_signup_success_and_cookie(client: AsyncClient) -> None:
    """P2-T02: Signup returns 201 with TokenResponse and sets ff_refresh cookie."""
    resp = await client.post(
        "/v1/auth/signup",
        json={
            "email": "Ada.Lovelace@example.com",
            "password": "Password123456!",
            "display_name": "Ada Lovelace",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "ada.lovelace@example.com"
    assert data["user"]["display_name"] == "Ada Lovelace"

    assert "ff_refresh" in resp.cookies
    set_cookie = resp.headers.get("set-cookie", "")
    assert "ff_refresh=" in set_cookie
    assert "Path=/v1/auth" in set_cookie
    assert "httponly" in set_cookie.lower()


@pytest.mark.asyncio
async def test_signup_validation_and_duplicate(client: AsyncClient) -> None:
    """P2-T03: Existing email (any case) -> 409 EMAIL_TAKEN; password < 12 -> 422."""
    # First signup
    res1 = await client.post(
        "/v1/auth/signup",
        json={"email": "ada@example.com", "password": "Password123456!", "display_name": "Ada"},
    )
    assert res1.status_code == 201

    # Duplicate email uppercase
    res2 = await client.post(
        "/v1/auth/signup",
        json={"email": "ADA@EXAMPLE.COM", "password": "Password123456!", "display_name": "Ada Dup"},
    )
    assert res2.status_code == 409
    assert res2.json()["code"] == "EMAIL_TAKEN"

    # Password of 11 characters
    res3 = await client.post(
        "/v1/auth/signup",
        json={"email": "short@example.com", "password": "Short12345!", "display_name": "Short"},
    )
    assert res3.status_code == 422
    assert res3.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_login_and_timing_defense(client: AsyncClient) -> None:
    """P2-T04: Login success; wrong password and unknown email return identical 401 bodies."""
    await client.post(
        "/v1/auth/signup",
        json={"email": "ada@example.com", "password": "Password123456!", "display_name": "Ada"},
    )

    # Valid login
    res_ok = await client.post(
        "/v1/auth/login",
        json={"email": "ada@example.com", "password": "Password123456!"},
    )
    assert res_ok.status_code == 200
    assert "access_token" in res_ok.json()

    # Wrong password
    res_bad_pw = await client.post(
        "/v1/auth/login",
        json={"email": "ada@example.com", "password": "WrongPassword123!"},
    )
    assert res_bad_pw.status_code == 401

    # Unknown email
    res_unknown = await client.post(
        "/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "WrongPassword123!"},
    )
    assert res_unknown.status_code == 401

    # Assert bodies match identically to prevent email enumeration
    assert res_bad_pw.json()["code"] == res_unknown.json()["code"] == "INVALID_CREDENTIALS"
    assert res_bad_pw.json()["detail"] == res_unknown.json()["detail"]


@pytest.mark.asyncio
async def test_me_endpoint_security(
    client: AsyncClient,
    integration_settings: Settings,
) -> None:
    """P2-T05: GET /v1/me rejects missing, expired, or invalid tokens."""
    # 1. No token
    res1 = await client.get("/v1/me")
    assert res1.status_code == 401
    assert res1.json()["code"] == "UNAUTHENTICATED"

    # 2. Expired token
    expired_payload = {
        "sub": str(uuid4()),
        "iat": int(time.time()) - 1000,
        "exp": int(time.time()) - 100,
        "iss": integration_settings.jwt_issuer,
        "aud": integration_settings.jwt_audience,
    }
    expired_token = jwt.encode(expired_payload, integration_settings.jwt_secret, algorithm="HS256")
    res2 = await client.get("/v1/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res2.status_code == 401

    # 3. Wrong issuer / audience / key
    wrong_key_token = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": int(time.time()),
            "exp": int(time.time()) + 1000,
            "iss": "wrong",
            "aud": "wrong",
        },
        "wrong-secret-key-that-does-not-match-at-all!",
        algorithm="HS256",
    )
    res3 = await client.get("/v1/me", headers={"Authorization": f"Bearer {wrong_key_token}"})
    assert res3.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_theft_mitigation(client: AsyncClient) -> None:
    """P2-T06: Refresh rotates token; presenting old revoked token revokes descendants."""
    signup_resp = await client.post(
        "/v1/auth/signup",
        json={
            "email": "rotator@example.com",
            "password": "Password123456!",
            "display_name": "Rotator",
        },
    )
    assert signup_resp.status_code == 201
    cookie_v1 = signup_resp.cookies["ff_refresh"]

    # First rotation (v1 -> v2)
    client.cookies.set("ff_refresh", cookie_v1, path="/v1/auth")
    ref1_resp = await client.post("/v1/auth/refresh", headers={"X-FlowForge-CSRF": "1"})
    assert ref1_resp.status_code == 200
    cookie_v2 = ref1_resp.cookies["ff_refresh"]
    assert cookie_v1 != cookie_v2

    # Reuse old revoked v1 cookie -> should fail and trigger revocation
    client.cookies.set("ff_refresh", cookie_v1, path="/v1/auth")
    stolen_resp = await client.post("/v1/auth/refresh", headers={"X-FlowForge-CSRF": "1"})
    assert stolen_resp.status_code == 401

    # Now even v2 should be revoked because the chain was terminated
    client.cookies.set("ff_refresh", cookie_v2, path="/v1/auth")
    v2_resp = await client.post("/v1/auth/refresh", headers={"X-FlowForge-CSRF": "1"})
    assert v2_resp.status_code == 401


@pytest.mark.asyncio
async def test_csrf_protection_and_logout(client: AsyncClient) -> None:
    """P2-T07: Refresh/logout without CSRF -> 403; logout clears cookie and is idempotent."""
    signup_resp = await client.post(
        "/v1/auth/signup",
        json={"email": "csrf@example.com", "password": "Password123456!", "display_name": "Csrf"},
    )
    assert signup_resp.status_code == 201
    cookie = signup_resp.cookies["ff_refresh"]
    client.cookies.set("ff_refresh", cookie, path="/v1/auth")

    # Missing CSRF header
    res_no_csrf = await client.post("/v1/auth/refresh")
    assert res_no_csrf.status_code == 403

    res_logout_no_csrf = await client.post("/v1/auth/logout")
    assert res_logout_no_csrf.status_code == 403

    # Valid logout with CSRF
    res_logout = await client.post("/v1/auth/logout", headers={"X-FlowForge-CSRF": "1"})
    assert res_logout.status_code == 204

    # Second logout without cookie is still 204
    client.cookies.clear()
    res_logout2 = await client.post("/v1/auth/logout", headers={"X-FlowForge-CSRF": "1"})
    assert res_logout2.status_code == 204
