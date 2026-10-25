"""Integration tests for keyset cursor pagination stability and limits (P2-T17 and P2-T18)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_workflow_keyset_pagination_stability(client: AsyncClient) -> None:
    """P2-T17: 30 workflows with limit=10 -> 3 distinct pages in descending order; insertion stable."""
    res_signup = await client.post(
        "/v1/auth/signup",
        json={"email": "pager@example.com", "password": "Password123456!", "display_name": "Pager"},
    )
    token = res_signup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post(
        "/v1/organizations", json={"name": "Pagination Org"}, headers=headers
    )
    org_id = org_res.json()["id"]

    # Create 30 workflows sequentially
    created_ids = []
    for i in range(30):
        resp = await client.post(
            f"/v1/organizations/{org_id}/workflows",
            json={"display_name": f"Workflow {i:02d}"},
            headers=headers,
        )
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])

    # Page 1
    p1_resp = await client.get(f"/v1/organizations/{org_id}/workflows?limit=10", headers=headers)
    assert p1_resp.status_code == 200
    p1 = p1_resp.json()
    assert len(p1["items"]) == 10
    assert p1["has_more"] is True
    assert p1["next_cursor"] is not None

    # Insert a brand new workflow in between page fetches
    await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Interleaved Workflow"},
        headers=headers,
    )

    # Page 2 using next_cursor from Page 1
    p2_resp = await client.get(
        f"/v1/organizations/{org_id}/workflows?limit=10&cursor={p1['next_cursor']}",
        headers=headers,
    )
    assert p2_resp.status_code == 200
    p2 = p2_resp.json()
    assert len(p2["items"]) == 10
    assert p2["has_more"] is True

    # Page 3 using next_cursor from Page 2
    p3_resp = await client.get(
        f"/v1/organizations/{org_id}/workflows?limit=10&cursor={p2['next_cursor']}",
        headers=headers,
    )
    assert p3_resp.status_code == 200
    p3 = p3_resp.json()
    assert len(p3["items"]) == 10
    assert p3["has_more"] is False
    assert p3["next_cursor"] is None

    # Assert no duplicates across the 30 original workflows
    page_ids = [w["id"] for w in p1["items"] + p2["items"] + p3["items"]]
    assert len(page_ids) == 30
    assert len(set(page_ids)) == 30

    # Assert descending order (most recently created first)
    assert page_ids == list(reversed(created_ids))


@pytest.mark.asyncio
async def test_pagination_boundary_and_bad_cursor_errors(client: AsyncClient) -> None:
    """P2-T18: Bad cursor -> 400; limit=0 and limit=101 -> 422."""
    res_signup = await client.post(
        "/v1/auth/signup",
        json={
            "email": "bounds@example.com",
            "password": "Password123456!",
            "display_name": "Bounds",
        },
    )
    token = res_signup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post("/v1/organizations", json={"name": "Bounds Org"}, headers=headers)
    org_id = org_res.json()["id"]

    # 1. Bad cursor -> 400 BAD_REQUEST
    res_bad_cursor = await client.get(
        f"/v1/organizations/{org_id}/workflows?cursor=invalid_base64_string",
        headers=headers,
    )
    assert res_bad_cursor.status_code == 400
    assert res_bad_cursor.json()["code"] == "BAD_REQUEST"

    # 2. limit = 0 -> 422 VALIDATION_ERROR
    res_zero = await client.get(
        f"/v1/organizations/{org_id}/workflows?limit=0",
        headers=headers,
    )
    assert res_zero.status_code == 422

    # 3. limit = 101 -> 422 VALIDATION_ERROR
    res_excess = await client.get(
        f"/v1/organizations/{org_id}/workflows?limit=101",
        headers=headers,
    )
    assert res_excess.status_code == 422
