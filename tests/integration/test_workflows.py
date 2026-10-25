"""Integration tests for workflow authoring, permissions, and tenancy isolation (P2-T14 to P2-T16)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.workflows.models import Workflow


async def _signup(client: AsyncClient, email: str) -> tuple[str, UUID]:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    assert res.status_code == 201
    return res.json()["access_token"], UUID(res.json()["user"]["id"])


@pytest.mark.asyncio
async def test_create_workflow_rbac(client: AsyncClient) -> None:
    """P2-T14: Owner/admin can create workflow (201); operator/reviewer/viewer cannot (403)."""
    tok_owner, _ = await _signup(client, "wf_owner@example.com")
    tok_admin, _ = await _signup(client, "wf_admin@example.com")
    tok_operator, _ = await _signup(client, "wf_operator@example.com")
    tok_viewer, _ = await _signup(client, "wf_viewer@example.com")

    # Create Org
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Workflow Studio"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    org_id = org_res.json()["id"]

    # Add roles
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "wf_admin@example.com", "role": "admin"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "wf_operator@example.com", "role": "operator"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "wf_viewer@example.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )

    # 1. Owner creates -> 201
    res_owner = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Triage Pipeline", "description": "Auto triage"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    assert res_owner.status_code == 201
    assert res_owner.json()["display_name"] == "Triage Pipeline"

    # 2. Admin creates -> 201
    res_admin = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Billing Pipeline"},
        headers={"Authorization": f"Bearer {tok_admin}"},
    )
    assert res_admin.status_code == 201

    # 3. Operator creates -> 403
    res_op = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Forbidden Op Pipeline"},
        headers={"Authorization": f"Bearer {tok_operator}"},
    )
    assert res_op.status_code == 403

    # 4. Viewer creates -> 403
    res_view = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Forbidden View Pipeline"},
        headers={"Authorization": f"Bearer {tok_viewer}"},
    )
    assert res_view.status_code == 403


@pytest.mark.asyncio
async def test_workflow_tenant_isolation_404(client: AsyncClient) -> None:
    """P2-T15: Org A workflow: GET /v1/workflows/{id} as Org B user -> 404; Org A viewer -> 200."""
    tok_a, _ = await _signup(client, "tenant_a@example.com")
    tok_viewer_a, _ = await _signup(client, "viewer_a@example.com")
    tok_b, _ = await _signup(client, "tenant_b@example.com")

    # Create Org A and workflow
    org_a = await client.post(
        "/v1/organizations",
        json={"name": "Org Alpha"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    org_a_id = org_a.json()["id"]

    await client.post(
        f"/v1/organizations/{org_a_id}/members",
        json={"email": "viewer_a@example.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )

    wf = await client.post(
        f"/v1/organizations/{org_a_id}/workflows",
        json={"display_name": "Secret Workflow"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    wf_id = wf.json()["id"]

    # Create Org B
    await client.post(
        "/v1/organizations",
        json={"name": "Org Beta"},
        headers={"Authorization": f"Bearer {tok_b}"},
    )

    # 1. Org B user accesses Org A's workflow -> 404 (NOT 403, hiding its existence)
    res_b = await client.get(
        f"/v1/workflows/{wf_id}",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert res_b.status_code == 404
    assert res_b.json()["code"] == "NOT_FOUND"

    # 2. Org A viewer accesses Org A's workflow -> 200
    res_viewer = await client.get(
        f"/v1/workflows/{wf_id}",
        headers={"Authorization": f"Bearer {tok_viewer_a}"},
    )
    assert res_viewer.status_code == 200
    assert res_viewer.json()["id"] == wf_id


@pytest.mark.asyncio
async def test_list_workflows_archived_filter(client: AsyncClient, db_session) -> None:
    """P2-T16: List workflows excludes archived by default; include_archived=true includes them."""
    tok_owner, _ = await _signup(client, "archive_test@example.com")
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Archive Studio"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    org_id = org_res.json()["id"]

    await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Active 1"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Active 2"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    wf3 = await client.post(
        f"/v1/organizations/{org_id}/workflows",
        json={"display_name": "Archived 1"},
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    wf3_id = UUID(wf3.json()["id"])

    # Mark wf3 as archived in DB
    await db_session.execute(
        update(Workflow).where(Workflow.id == wf3_id).values(archived_at=datetime.now(UTC))
    )
    await db_session.commit()

    # Default query excludes archived
    res_default = await client.get(
        f"/v1/organizations/{org_id}/workflows",
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    assert res_default.status_code == 200
    names_default = [w["display_name"] for w in res_default.json()["items"]]
    assert "Archived 1" not in names_default
    assert set(names_default) == {"Active 1", "Active 2"}

    # With include_archived=true
    res_archived = await client.get(
        f"/v1/organizations/{org_id}/workflows?include_archived=true",
        headers={"Authorization": f"Bearer {tok_owner}"},
    )
    assert res_archived.status_code == 200
    names_all = [w["display_name"] for w in res_archived.json()["items"]]
    assert "Archived 1" in names_all
    assert len(names_all) == 3
