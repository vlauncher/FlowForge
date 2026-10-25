"""Integration tests for credentials vault and RBAC isolation (P5-T04)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings


async def create_user_and_token(client: AsyncClient, email: str) -> tuple[str, str]:
    """Helper to create user and return (user_id, access_token)."""
    resp = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": "Password123456!",
            "display_name": email.split("@")[0],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["user"]["id"], data["access_token"]


@pytest.mark.asyncio
async def test_credentials_lifecycle_encryption_and_rbac(
    client: AsyncClient,
    db_engine: AsyncEngine,
    integration_settings: Settings,
) -> None:
    """P5-T04: Create credential -> 201 without secret in JSON; DB encrypted; GET metadata; viewer 403."""
    # 1. Setup Owner user & organization
    _, owner_token = await create_user_and_token(client, "cred_owner@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    org_resp = await client.post(
        "/v1/organizations",
        json={"name": "Credentials Org"},
        headers=owner_headers,
    )
    assert org_resp.status_code == 201
    org_id = org_resp.json()["id"]

    # 2. Setup Viewer user
    viewer_id, viewer_token = await create_user_and_token(client, "cred_viewer@example.com")
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    # Add viewer to org
    add_mem_resp = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "cred_viewer@example.com", "role": "viewer"},
        headers=owner_headers,
    )
    assert add_mem_resp.status_code == 201

    # 3. Viewer attempts to create credential -> 403 FORBIDDEN
    secret_value = "sk_live_super_secret_token_12345"
    cred_payload = {
        "name": "stripe_prod",
        "provider": "stripe",
        "secret": secret_value,
        "allowed_hosts": ["api.stripe.com"],
        "permission_scopes": ["charges:write", "customers:read"],
    }
    viewer_create_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json=cred_payload,
        headers=viewer_headers,
    )
    assert viewer_create_resp.status_code == 403

    # Viewer attempts to list credentials -> 403 FORBIDDEN
    viewer_list_resp = await client.get(
        f"/v1/organizations/{org_id}/credentials",
        headers=viewer_headers,
    )
    assert viewer_list_resp.status_code == 403

    # 4. Owner creates credential -> 201 CREATED
    owner_create_resp = await client.post(
        f"/v1/organizations/{org_id}/credentials",
        json=cred_payload,
        headers=owner_headers,
    )
    assert owner_create_resp.status_code == 201
    cred_data = owner_create_resp.json()

    # Verify response schema does NOT contain secret
    assert "secret" not in cred_data
    assert "encrypted_secret" not in cred_data
    assert cred_data["name"] == "stripe_prod"
    assert cred_data["provider"] == "stripe"
    assert cred_data["allowed_hosts"] == ["api.stripe.com"]
    assert cred_data["permission_scopes"] == ["charges:write", "customers:read"]
    assert cred_data["key_id"] == "k1"
    assert cred_data["rotated_at"] is None
    assert "id" in cred_data
    assert "created_at" in cred_data
    cred_id = cred_data["id"]

    # 5. Verify direct database storage is AES-256-GCM encrypted and does not contain plaintext bytes
    async with db_engine.connect() as conn:
        res = await conn.execute(
            text("SELECT encrypted_secret, key_id FROM integration_credentials WHERE id = :id"),
            {"id": cred_id},
        )
        row = res.mappings().first()
        assert row is not None
        encrypted_secret_bytes = bytes(row["encrypted_secret"])
        assert secret_value.encode("utf-8") not in encrypted_secret_bytes
        assert row["key_id"] == "k1"

    # 6. Owner lists credentials -> 200 OK
    list_resp = await client.get(
        f"/v1/organizations/{org_id}/credentials",
        headers=owner_headers,
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert len(list_data["items"]) == 1
    item = list_data["items"][0]
    assert item["id"] == cred_id
    assert "secret" not in item
    assert "encrypted_secret" not in item
