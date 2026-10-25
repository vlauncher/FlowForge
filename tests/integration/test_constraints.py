"""Integration tests for database constraints, triggers, and rollback invariants (P2-T19 to P2-T23)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.modules.identity.models import User
from app.modules.organizations.models import Membership, Organization
from app.modules.workflows.models import Workflow, WorkflowVersion


@pytest.mark.asyncio
async def test_duplicate_membership_rejected_by_db(db_session) -> None:
    """P2-T19: Duplicate (org_id, user_id) membership violates database unique constraint."""
    user = User(email="test_dup@example.com", password_hash="hash", display_name="Dup")
    org = Organization(name="Dup Org", slug="dup-org")
    db_session.add_all([user, org])
    await db_session.flush()

    mem1 = Membership(org_id=org.id, user_id=user.id, role="owner")
    db_session.add(mem1)
    await db_session.commit()

    # Second identical membership
    mem2 = Membership(org_id=org.id, user_id=user.id, role="viewer")
    db_session.add(mem2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_workflow_version_constraints(db_session) -> None:
    """P2-T20: (workflow_id, version) uniqueness and published CHECK constraints enforced."""
    org = Organization(name="Version Org", slug="ver-org")
    db_session.add(org)
    await db_session.flush()
    org_id = org.id

    wf = Workflow(org_id=org_id, display_name="Test Flow")
    db_session.add(wf)
    await db_session.flush()
    wf_id = wf.id

    v1 = WorkflowVersion(
        workflow_id=wf_id,
        org_id=org_id,
        version=1,
        status="draft",
        definition_json={"steps": []},
    )
    db_session.add(v1)
    await db_session.commit()

    # 1. Duplicate version 1
    v1_dup = WorkflowVersion(
        workflow_id=wf_id,
        org_id=org_id,
        version=1,
        status="draft",
        definition_json={"steps": []},
    )
    db_session.add(v1_dup)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 2. Published status without checksum or published_at violates CHECK constraint
    v2_bad_pub = WorkflowVersion(
        workflow_id=wf_id,
        org_id=org_id,
        version=2,
        status="published",
        definition_json={"steps": []},
        checksum=None,
        published_at=None,
    )
    db_session.add(v2_bad_pub)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_published_workflow_immutability_trigger(db_session) -> None:
    """P2-T21: Database trigger blocks UPDATE and DELETE on published workflow versions."""
    org = Organization(name="Trigger Org", slug="trig-org")
    db_session.add(org)
    await db_session.flush()
    org_id = org.id

    wf = Workflow(org_id=org_id, display_name="Immutability Flow")
    db_session.add(wf)
    await db_session.flush()
    wf_id = wf.id

    now = datetime.now(UTC)
    v_published = WorkflowVersion(
        workflow_id=wf_id,
        org_id=org_id,
        version=1,
        status="published",
        definition_json={"steps": ["a"]},
        checksum="sha256-dummy-hash",
        published_at=now,
    )
    v_draft = WorkflowVersion(
        workflow_id=wf_id,
        org_id=org_id,
        version=2,
        status="draft",
        definition_json={"steps": ["b"]},
    )
    db_session.add_all([v_published, v_draft])
    await db_session.commit()

    v_published_id = v_published.id
    v_draft_id = v_draft.id

    # 1. Draft can be updated
    await db_session.execute(
        update(WorkflowVersion)
        .where(WorkflowVersion.id == v_draft_id)
        .values(definition_json={"steps": ["b", "updated"]})
    )
    await db_session.commit()

    # 2. Update published row -> raises exception from trigger (SQLSTATE P0001)
    with pytest.raises(DBAPIError) as exc_info:
        await db_session.execute(
            update(WorkflowVersion)
            .where(WorkflowVersion.id == v_published_id)
            .values(checksum="tampered")
        )
        await db_session.commit()
    assert "published workflow versions are immutable" in str(exc_info.value)
    await db_session.rollback()

    # 3. Delete published row -> raises exception from trigger
    with pytest.raises(DBAPIError) as exc_info_del:
        await db_session.execute(
            delete(WorkflowVersion).where(WorkflowVersion.id == v_published_id)
        )
        await db_session.commit()
    assert "published workflow versions are immutable" in str(exc_info_del.value)


@pytest.mark.asyncio
async def test_single_draft_partial_index(db_session) -> None:
    """P2-T22: Multiple draft versions for a single workflow are rejected by partial index."""
    org = Organization(name="Draft Org", slug="draft-org")
    db_session.add(org)
    await db_session.flush()

    wf = Workflow(org_id=org.id, display_name="Draft Flow")
    db_session.add(wf)
    await db_session.flush()

    d1 = WorkflowVersion(
        workflow_id=wf.id,
        org_id=org.id,
        version=1,
        status="draft",
        definition_json={},
    )
    db_session.add(d1)
    await db_session.commit()

    d2 = WorkflowVersion(
        workflow_id=wf.id,
        org_id=org.id,
        version=2,
        status="draft",
        definition_json={},
    )
    db_session.add(d2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_transaction_rollback_on_service_exception(db_session) -> None:
    """P2-T23: Exception inside a service transaction cleanly rolls back intermediate inserts."""
    user = User(email="rollback_user@example.com", password_hash="hash", display_name="Rollback")
    db_session.add(user)
    await db_session.commit()

    # Start explicit transaction block
    try:
        org = Organization(name="Will Roll Back", slug="rollback-org")
        db_session.add(org)
        await db_session.flush()

        # Simulate deliberate failure before commit
        raise RuntimeError("Simulated mid-operation transaction failure")
    except RuntimeError:
        await db_session.rollback()

    # Verify org row was not committed
    res = await db_session.execute(select(Organization).where(Organization.slug == "rollback-org"))
    assert res.scalar_one_or_none() is None
