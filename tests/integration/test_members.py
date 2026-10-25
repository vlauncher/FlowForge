"""Integration tests for organization member management and last-owner safety (P2-T11 to P2-T13)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from httpx import AsyncClient


async def _signup(client: AsyncClient, email: str) -> tuple[str, UUID]:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    assert res.status_code == 201
    return res.json()["access_token"], UUID(res.json()["user"]["id"])


@pytest.mark.asyncio
async def test_add_member_rbac_and_errors(client: AsyncClient) -> None:
    """P2-T11: Admin adds member; duplicate -> 409; unknown email -> 404; viewer adding -> 403."""
    tok_owner, _ = await _signup(client, "owner@example.com")
    tok_admin, _ = await _signup(client, "admin@example.com")
    tok_viewer, _ = await _signup(client, "viewer@example.com")
    tok_candidate, _ = await _signup(client, "candidate@example.com")

    # Create org as owner
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Engineering Team"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    org_id = org_res.json()["id"]

    # Owner adds admin
    add_admin = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "admin@example.com", "role": "admin"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    assert add_admin.status_code == 201

    # Owner adds viewer
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "viewer@example.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )

    # 1. Admin adds candidate as operator (allowed)
    res_add = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "candidate@example.com", "role": "operator"},
        headers={"Authorization": f"Bearer {tok_admin}"},
    )
    assert res_add.status_code == 201
    assert res_add.json()["role"] == "operator"

    # 2. Duplicate member -> 409 CONFLICT
    res_dup = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "candidate@example.com", "role": "operator"},
        headers={"Authorization": f"Bearer {tok_admin}"},
    )
    assert res_dup.status_code == 409
    assert res_dup.json()["code"] == "CONFLICT"

    # 3. Unknown email -> 404 NOT_FOUND
    res_unknown = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "nonexistent_person@example.com", "role": "operator"},
        headers={"Authorization": f"Bearer {tok_admin}"},
    )
    assert res_unknown.status_code == 404

    # 4. Viewer trying to add member -> 403 FORBIDDEN
    res_viewer_add = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "candidate2@example.com", "role": "operator"},
        headers={"Authorization": f"Bearer {tok_viewer}"},
    )
    assert res_viewer_add.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_grant_or_alter_owner(client: AsyncClient) -> None:
    """P2-T12: Admin cannot grant owner role or modify an owner's role -> 403."""
    tok_owner, uid_owner = await _signup(client, "root_owner@example.com")
    tok_admin, _ = await _signup(client, "root_admin@example.com")
    tok_user, _ = await _signup(client, "regular_user@example.com")

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Security Org"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    org_id = org_res.json()["id"]

    # Add admin
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "root_admin@example.com", "role": "admin"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )

    # 1. Admin attempts to grant owner role
    res_grant = await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "regular_user@example.com", "role": "owner"},
        headers={"Authorization": f"Bearer {tok_admin}"},
    )
    assert res_grant.status_code == 403

    # 2. Admin attempts to alter existing owner role
    res_demote = await client.patch(
        f"/v1/organizations/{org_id}/members/{uid_owner}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {tok_admin}"},
    )
    assert res_demote.status_code == 403


@pytest.mark.asyncio
async def test_last_owner_protection_and_concurrency(client: AsyncClient) -> None:
    """P2-T13: Demoting last owner -> 409 LAST_OWNER; concurrent demotion leaves >= 1 owner."""
    tok_owner1, uid_owner1 = await _signup(client, "owner1@example.com")
    tok_owner2, uid_owner2 = await _signup(client, "owner2@example.com")

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Dual Owner Org"},
        headers={"Authorization": f"Bearer {tok_owner1}"},
    )
    org_id = org_res.json()["id"]

    # 1. Sole owner attempts self-demotion -> 409 LAST_OWNER
    res_sole = await client.patch(
        f"/v1/organizations/{org_id}/members/{uid_owner1}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {tok_owner1}"},
    )
    assert res_sole.status_code == 409
    assert res_sole.json()["code"] == "LAST_OWNER"

    # Add second owner
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "owner2@example.com", "role": "owner"},
        headers={"Authorization": f"Bearer {tok_owner1}"},
    )

    # 2. Concurrent demotion: two simultaneous requests attempt to demote both owners
    req1 = client.patch(
        f"/v1/organizations/{org_id}/members/{uid_owner1}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {tok_owner1}"},
    )
    req2 = client.patch(
        f"/v1/organizations/{org_id}/members/{uid_owner2}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {tok_owner2}"},
    )

    res1, res2 = await asyncio.gather(req1, req2)
    statuses = {res1.status_code, res2.status_code}

    # Due to SELECT FOR UPDATE pessimistic locking, exactly one demotion succeeds (200)
    # and the other demotion is rejected as last owner (409)
    assert statuses == {200, 409}
