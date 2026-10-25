"""Integration tests for organization creation and tenant isolation (P2-T08 to P2-T10)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _signup(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    assert res.status_code == 201
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_create_org_and_slug_generation(client: AsyncClient) -> None:
    """P2-T08: Creator becomes owner; slug auto-derived; duplicate explicit slug -> 409."""
    token = await _signup(client, "user_org@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create with auto slug
    res = await client.post(
        "/v1/organizations",
        json={"name": "Acme Aerospace Corp"},
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Acme Aerospace Corp"
    assert data["slug"] == "acme-aerospace-corp"
    assert data["my_role"] == "owner"

    # 2. Second org with same name gets suffixed slug
    res2 = await client.post(
        "/v1/organizations",
        json={"name": "Acme Aerospace Corp"},
        headers=headers,
    )
    assert res2.status_code == 201
    assert res2.json()["slug"] == "acme-aerospace-corp-2"

    # 3. Explicit duplicate slug
    res3 = await client.post(
        "/v1/organizations",
        json={"name": "Another Corp", "slug": "acme-aerospace-corp"},
        headers=headers,
    )
    assert res3.status_code == 409
    assert res3.json()["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_list_user_organizations_filtering(client: AsyncClient) -> None:
    """P2-T09: GET /v1/organizations returns only organizations caller belongs to."""
    tok_a = await _signup(client, "user_a@example.com")
    tok_b = await _signup(client, "user_b@example.com")

    # A creates 2 orgs
    await client.post(
        "/v1/organizations",
        json={"name": "Org A1"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    await client.post(
        "/v1/organizations",
        json={"name": "Org A2"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )

    # B creates 1 org
    await client.post(
        "/v1/organizations",
        json={"name": "Org B1"},
        headers={"Authorization": f"Bearer {tok_b}"},
    )

    # List as A
    res_a = await client.get("/v1/organizations", headers={"Authorization": f"Bearer {tok_a}"})
    assert res_a.status_code == 200
    names_a = [org["name"] for org in res_a.json()["items"]]
    assert set(names_a) == {"Org A1", "Org A2"}

    # List as B
    res_b = await client.get("/v1/organizations", headers={"Authorization": f"Bearer {tok_b}"})
    assert res_b.status_code == 200
    names_b = [org["name"] for org in res_b.json()["items"]]
    assert names_b == ["Org B1"]


@pytest.mark.asyncio
async def test_foreign_org_lookup_returns_404_not_403(client: AsyncClient) -> None:
    """P2-T10: User B requesting Org A returns 404 NOT_FOUND to hide org existence."""
    tok_a = await _signup(client, "owner_a@example.com")
    tok_b = await _signup(client, "intruder_b@example.com")

    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Secret Org A"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    org_id = org_res.json()["id"]

    # Intruder B requests Org A
    res = await client.get(
        f"/v1/organizations/{org_id}",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"
