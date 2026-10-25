"""Integration tests for audit events: immutability trigger and query endpoint (P7-T09, P7-T10)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


async def signup_user(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_audit_events_immutability_trigger(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """P7-T09: Mutating actions write audit_events; UPDATE or DELETE fails in PostgreSQL with P0002."""
    owner_token = await signup_user(client, "audit_imm_owner@example.com")

    # Creating an org writes an audit event (action: organization.created)
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Audit Imm Org", "slug": "audit-imm-org"},
        headers={"Authorization": f"Bearer {owner_token}", "X-Request-ID": "req-imm-001"},
    )
    assert org_res.status_code == 201
    org_id = org_res.json()["id"]

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # Verify audit event exists with request_id and metadata
    async with session_factory() as session:
        res = await session.execute(
            text("SELECT id, action, request_id FROM audit_events WHERE org_id = :org_id"),
            {"org_id": org_id},
        )
        row = res.fetchone()
        assert row is not None
        event_id, action, request_id = row
        assert action == "org.created"
        assert request_id == "req-imm-001"

    # Attempt raw SQL UPDATE on audit_events -> MUST FAIL with P0002
    async with session_factory() as session:
        with pytest.raises(DBAPIError) as exc_info:
            await session.execute(
                text("UPDATE audit_events SET action = 'tampered' WHERE id = :event_id"),
                {"event_id": event_id},
            )
            await session.commit()
        # Verify pgcode is P0002 or exception message mentions append-only
        err_msg = str(exc_info.value)
        orig = getattr(exc_info.value, "orig", None)
        pgcode = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
        assert pgcode == "P0002" or "audit_events is append-only" in err_msg

    # Attempt raw SQL DELETE on audit_events -> MUST FAIL with P0002
    async with session_factory() as session:
        with pytest.raises(DBAPIError) as exc_info:
            await session.execute(
                text("DELETE FROM audit_events WHERE id = :event_id"),
                {"event_id": event_id},
            )
            await session.commit()
        err_msg = str(exc_info.value)
        orig = getattr(exc_info.value, "orig", None)
        pgcode = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
        assert pgcode == "P0002" or "audit_events is append-only" in err_msg


@pytest.mark.asyncio
async def test_audit_events_query_roles_and_pagination(
    client: AsyncClient,
) -> None:
    """P7-T10: GET /audit-events returns 200 for owner/admin, 403 for operator/reviewer/viewer, 404 for non-member."""
    owner_token = await signup_user(client, "audit_owner@example.com")
    admin_token = await signup_user(client, "audit_admin@example.com")
    reviewer_token = await signup_user(client, "audit_reviewer@example.com")
    operator_token = await signup_user(client, "audit_operator@example.com")
    viewer_token = await signup_user(client, "audit_viewer@example.com")
    stranger_token = await signup_user(client, "audit_stranger@example.com")

    # Create org
    org_res = await client.post(
        "/v1/organizations",
        json={"name": "Audit Query Corp", "slug": "audit-query-corp"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    org_id = org_res.json()["id"]

    # Add members
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "audit_admin@example.com", "role": "admin"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "audit_reviewer@example.com", "role": "reviewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "audit_operator@example.com", "role": "operator"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        f"/v1/organizations/{org_id}/members",
        json={"email": "audit_viewer@example.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # 1. Owner queries -> 200
    res_owner = await client.get(
        f"/v1/organizations/{org_id}/audit-events",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_owner.status_code == 200
    events = res_owner.json()["items"]
    assert len(events) >= 5  # org created + 4 members added

    # 2. Admin queries -> 200
    res_admin = await client.get(
        f"/v1/organizations/{org_id}/audit-events",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200

    # 3. Reviewer queries -> 403
    res_reviewer = await client.get(
        f"/v1/organizations/{org_id}/audit-events",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert res_reviewer.status_code == 403

    # 4. Operator queries -> 403
    res_operator = await client.get(
        f"/v1/organizations/{org_id}/audit-events",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert res_operator.status_code == 403

    # 5. Viewer queries -> 403
    res_viewer = await client.get(
        f"/v1/organizations/{org_id}/audit-events",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_viewer.status_code == 403

    # 6. Non-member stranger queries -> 404
    res_stranger = await client.get(
        f"/v1/organizations/{org_id}/audit-events",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert res_stranger.status_code == 404

    # 7. Action filter and pagination
    res_filtered = await client.get(
        f"/v1/organizations/{org_id}/audit-events?action=org.created",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_filtered.status_code == 200
    assert len(res_filtered.json()["items"]) == 1
    assert res_filtered.json()["items"][0]["action"] == "org.created"

    res_page1 = await client.get(
        f"/v1/organizations/{org_id}/audit-events?limit=2",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_page1.status_code == 200
    p1_items = res_page1.json()["items"]
    assert len(p1_items) == 2
    cursor = res_page1.json().get("next_cursor")
    assert cursor is not None

    res_page2 = await client.get(
        f"/v1/organizations/{org_id}/audit-events?limit=2&cursor={cursor}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_page2.status_code == 200
    p2_items = res_page2.json()["items"]
    assert len(p2_items) == 2
    assert p1_items[0]["id"] != p2_items[0]["id"]
