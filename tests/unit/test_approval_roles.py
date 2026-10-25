"""Unit tests for approval role hierarchy and decide permissions (P7-T01)."""

from __future__ import annotations

from app.domain.permissions import (
    Action,
    Role,
    can_decide_approval,
    has_permission,
)


def test_approval_permission_matrix() -> None:
    """Only reviewer, admin, and owner have Action.APPROVAL_DECIDE."""
    assert has_permission(Role.OWNER, Action.APPROVAL_DECIDE) is True
    assert has_permission(Role.ADMIN, Action.APPROVAL_DECIDE) is True
    assert has_permission(Role.REVIEWER, Action.APPROVAL_DECIDE) is True
    assert has_permission(Role.OPERATOR, Action.APPROVAL_DECIDE) is False
    assert has_permission(Role.VIEWER, Action.APPROVAL_DECIDE) is False


def test_reviewer_can_only_decide_reviewer_assigned_role() -> None:
    """Reviewer can decide reviewer tasks, but cannot decide admin or owner tasks."""
    assert can_decide_approval(Role.REVIEWER, "reviewer") is True
    assert can_decide_approval(Role.REVIEWER, "admin") is False
    assert can_decide_approval(Role.REVIEWER, "owner") is False


def test_admin_can_decide_reviewer_and_admin_not_owner() -> None:
    """Admin can decide reviewer and admin tasks, but cannot decide owner tasks."""
    assert can_decide_approval(Role.ADMIN, "reviewer") is True
    assert can_decide_approval(Role.ADMIN, "admin") is True
    assert can_decide_approval(Role.ADMIN, "owner") is False


def test_owner_can_decide_all_roles() -> None:
    """Owner can decide reviewer, admin, and owner tasks."""
    assert can_decide_approval(Role.OWNER, "reviewer") is True
    assert can_decide_approval(Role.OWNER, "admin") is True
    assert can_decide_approval(Role.OWNER, "owner") is True


def test_operator_and_viewer_denied_on_all_approvals() -> None:
    """Operator and viewer cannot decide any approvals."""
    for assigned in ("reviewer", "admin", "owner"):
        assert can_decide_approval(Role.OPERATOR, assigned) is False
        assert can_decide_approval(Role.VIEWER, assigned) is False
