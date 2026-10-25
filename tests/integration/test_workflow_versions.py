"""Integration tests for workflow versions, draft editing, and immutable publishing (P3-T12 to P3-T16)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def get_auth_token(client: AsyncClient, email: str) -> str:
    signup_res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return signup_res.json()["access_token"]


def valid_definition() -> dict:
    return {
        "schema_version": 1,
        "name": "Linear flow",
        "start": "step_a",
        "steps": [
            {
                "id": "step_a",
                "type": "set_data",
                "config": {"values": {"k": "v"}},
                "next": "step_b",
            },
            {
                "id": "step_b",
                "type": "set_data",
                "config": {"values": {"status": "ok"}},
                "next": None,
            },
        ],
    }


def invalid_cycle_definition() -> dict:
    return {
        "schema_version": 1,
        "name": "Cycle flow",
        "start": "step_a",
        "steps": [
            {"id": "step_a", "type": "set_data", "config": {"values": {}}, "next": "step_b"},
            {"id": "step_b", "type": "set_data", "config": {"values": {}}, "next": "step_a"},
        ],
    }


@pytest.mark.asyncio
async def test_draft_lifecycle_and_conflict(client: AsyncClient) -> None:
    """P3-T12: Create draft v1 -> 201; creating second draft -> 409 DRAFT_EXISTS; PUT updates v1 draft -> 200."""
    token = await get_auth_token(client, "author@example.com")
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Create org
    org_res = await client.post(
        "/v1/organizations", json={"name": "Draft Org"}, headers=auth_headers
    )
    org_id = org_res.json()["id"]

    # Create workflow
    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Test Workflow"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    # 1. Create first draft v1
    v1_res = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_definition()},
        headers=auth_headers,
    )
    assert v1_res.status_code == 201
    v1_data = v1_res.json()
    assert v1_data["version"] == 1
    assert v1_data["status"] == "draft"
    assert v1_data["checksum"] is None

    # 2. Attempt to create second draft while v1 is still draft -> 409 DRAFT_EXISTS
    v2_res = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_definition()},
        headers=auth_headers,
    )
    assert v2_res.status_code == 409
    assert v2_res.json()["code"] == "DRAFT_EXISTS"

    # 3. PUT updates v1 draft in place -> 200
    updated_def = valid_definition()
    updated_def["name"] = "Updated flow name"
    put_res = await client.put(
        f"/v1/workflows/{wf_id}/versions/1",
        json={"definition": updated_def},
        headers=auth_headers,
    )
    assert put_res.status_code == 200
    assert put_res.json()["definition_json"]["name"] == "Updated flow name"


@pytest.mark.asyncio
async def test_publish_invalid_draft_fails(client: AsyncClient) -> None:
    """P3-T13: Publish invalid draft (cycle) -> 422 GRAPH_CYCLE, remains draft, current_version_id remains null."""
    token = await get_auth_token(client, "cycle_tester@example.com")
    auth_headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post(
        "/v1/organizations", json={"name": "Cycle Org"}, headers=auth_headers
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Cycle Workflow"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    # Create draft with cycle
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": invalid_cycle_definition()},
        headers=auth_headers,
    )

    # Publish draft -> 422 GRAPH_CYCLE
    pub_res = await client.post(
        f"/v1/workflows/{wf_id}/publish",
        json={},
        headers=auth_headers,
    )
    assert pub_res.status_code == 422
    err_body = pub_res.json()
    assert err_body["code"] == "GRAPH_CYCLE"
    assert "errors" in err_body
    assert any(e["code"] == "GRAPH_CYCLE" for e in err_body["errors"])

    # Verify workflow state: current_version_id remains null
    wf_check = await client.get(f"/v1/workflows/{wf_id}", headers=auth_headers)
    assert wf_check.json()["current_version_id"] is None


@pytest.mark.asyncio
async def test_publish_valid_draft_success(client: AsyncClient) -> None:
    """P3-T14: Publish valid draft v1 -> 200, status=published, checksum set, current_version_id=v1.id."""
    token = await get_auth_token(client, "publisher@example.com")
    auth_headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post(
        "/v1/organizations", json={"name": "Publish Org"}, headers=auth_headers
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Publish Workflow"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    # Create draft
    draft_res = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_definition()},
        headers=auth_headers,
    )
    version_id = draft_res.json()["id"]

    # Publish
    pub_res = await client.post(
        f"/v1/workflows/{wf_id}/publish",
        json={},
        headers=auth_headers,
    )
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert pub_data["status"] == "published"
    assert pub_data["checksum"] is not None
    assert pub_data["published_at"] is not None

    # Check workflow now points to version
    wf_check = await client.get(f"/v1/workflows/{wf_id}", headers=auth_headers)
    assert wf_check.json()["current_version_id"] == version_id


@pytest.mark.asyncio
async def test_published_version_immutable_and_v2_draft(client: AsyncClient) -> None:
    """P3-T15: PUT /versions/1 after published -> 409 INVALID_STATE_TRANSITION; new draft creates version=2."""
    token = await get_auth_token(client, "immutability@example.com")
    auth_headers = {"Authorization": f"Bearer {token}"}

    org_res = await client.post(
        "/v1/organizations", json={"name": "Immutable Org"}, headers=auth_headers
    )
    org_id = org_res.json()["id"]

    wf_res = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Immutable Workflow"},
        headers=auth_headers,
    )
    wf_id = wf_res.json()["id"]

    # Create v1 and publish
    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_definition()},
        headers=auth_headers,
    )
    await client.post(f"/v1/workflows/{wf_id}/publish", json={}, headers=auth_headers)

    # 1. Attempt PUT on published version -> 409
    put_res = await client.put(
        f"/v1/workflows/{wf_id}/versions/1",
        json={"definition": valid_definition()},
        headers=auth_headers,
    )
    assert put_res.status_code == 409
    assert put_res.json()["code"] == "INVALID_STATE_TRANSITION"

    # 2. Creating new draft now succeeds with version=2
    v2_res = await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_definition()},
        headers=auth_headers,
    )
    assert v2_res.status_code == 201
    assert v2_res.json()["version"] == 2
    assert v2_res.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_cross_tenant_workflow_versions_access_denied(client: AsyncClient) -> None:
    """P3-T16: Cross-tenant user calling validate or publish on org A workflow -> 404."""
    tok_a = await get_auth_token(client, "owner_a@example.com")
    tok_b = await get_auth_token(client, "owner_b@example.com")

    # Org A creates workflow and draft
    org_a = await client.post(
        "/v1/organizations",
        json={"name": "Org A"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    org_a_id = org_a.json()["id"]

    wf = await client.post(
        f"/v1/organizations/{org_a_id}/workflows",
        json={"display_name": "Org A Workflow"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    wf_id = wf.json()["id"]

    await client.post(
        f"/v1/workflows/{wf_id}/versions",
        json={"definition": valid_definition()},
        headers={"Authorization": f"Bearer {tok_a}"},
    )

    # User B attempts to access Org A workflow:
    # 1. Validate -> 404
    val_res = await client.post(
        f"/v1/workflows/{wf_id}/validate",
        json={"definition": valid_definition()},
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert val_res.status_code == 404

    # 2. Publish -> 404
    pub_res = await client.post(
        f"/v1/workflows/{wf_id}/publish",
        json={},
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert pub_res.status_code == 404

    # 3. Get version -> 404
    get_res = await client.get(
        f"/v1/workflows/{wf_id}/versions/1",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert get_res.status_code == 404
