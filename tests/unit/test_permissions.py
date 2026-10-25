"""Unit tests for the RBAC permission matrix (P2-T25)."""

from __future__ import annotations

import pytest

from app.domain.permissions import (
    Action,
    Role,
    can_decide_approval,
    can_manage_member_role,
    has_permission,
)

# Reference table matching spec/00-global.md §2 exactly
EXPECTED_MATRIX: dict[tuple[Role, Action], bool] = {
    # org.manage
    (Role.OWNER, Action.ORG_MANAGE): True,
    (Role.ADMIN, Action.ORG_MANAGE): True,
    (Role.OPERATOR, Action.ORG_MANAGE): False,
    (Role.REVIEWER, Action.ORG_MANAGE): False,
    (Role.VIEWER, Action.ORG_MANAGE): False,
    # member.manage
    (Role.OWNER, Action.MEMBER_MANAGE): True,
    (Role.ADMIN, Action.MEMBER_MANAGE): True,
    (Role.OPERATOR, Action.MEMBER_MANAGE): False,
    (Role.REVIEWER, Action.MEMBER_MANAGE): False,
    (Role.VIEWER, Action.MEMBER_MANAGE): False,
    # credential.manage
    (Role.OWNER, Action.CREDENTIAL_MANAGE): True,
    (Role.ADMIN, Action.CREDENTIAL_MANAGE): True,
    (Role.OPERATOR, Action.CREDENTIAL_MANAGE): False,
    (Role.REVIEWER, Action.CREDENTIAL_MANAGE): False,
    (Role.VIEWER, Action.CREDENTIAL_MANAGE): False,
    # workflow.write
    (Role.OWNER, Action.WORKFLOW_WRITE): True,
    (Role.ADMIN, Action.WORKFLOW_WRITE): True,
    (Role.OPERATOR, Action.WORKFLOW_WRITE): False,
    (Role.REVIEWER, Action.WORKFLOW_WRITE): False,
    (Role.VIEWER, Action.WORKFLOW_WRITE): False,
    # workflow.publish
    (Role.OWNER, Action.WORKFLOW_PUBLISH): True,
    (Role.ADMIN, Action.WORKFLOW_PUBLISH): True,
    (Role.OPERATOR, Action.WORKFLOW_PUBLISH): False,
    (Role.REVIEWER, Action.WORKFLOW_PUBLISH): False,
    (Role.VIEWER, Action.WORKFLOW_PUBLISH): False,
    # workflow.read
    (Role.OWNER, Action.WORKFLOW_READ): True,
    (Role.ADMIN, Action.WORKFLOW_READ): True,
    (Role.OPERATOR, Action.WORKFLOW_READ): True,
    (Role.REVIEWER, Action.WORKFLOW_READ): True,
    (Role.VIEWER, Action.WORKFLOW_READ): True,
    # run.trigger
    (Role.OWNER, Action.RUN_TRIGGER): True,
    (Role.ADMIN, Action.RUN_TRIGGER): True,
    (Role.OPERATOR, Action.RUN_TRIGGER): True,
    (Role.REVIEWER, Action.RUN_TRIGGER): False,
    (Role.VIEWER, Action.RUN_TRIGGER): False,
    # run.cancel
    (Role.OWNER, Action.RUN_CANCEL): True,
    (Role.ADMIN, Action.RUN_CANCEL): True,
    (Role.OPERATOR, Action.RUN_CANCEL): True,
    (Role.REVIEWER, Action.RUN_CANCEL): False,
    (Role.VIEWER, Action.RUN_CANCEL): False,
    # run.retry
    (Role.OWNER, Action.RUN_RETRY): True,
    (Role.ADMIN, Action.RUN_RETRY): True,
    (Role.OPERATOR, Action.RUN_RETRY): True,
    (Role.REVIEWER, Action.RUN_RETRY): False,
    (Role.VIEWER, Action.RUN_RETRY): False,
    # run.read
    (Role.OWNER, Action.RUN_READ): True,
    (Role.ADMIN, Action.RUN_READ): True,
    (Role.OPERATOR, Action.RUN_READ): True,
    (Role.REVIEWER, Action.RUN_READ): True,
    (Role.VIEWER, Action.RUN_READ): True,
    # approval.read
    (Role.OWNER, Action.APPROVAL_READ): True,
    (Role.ADMIN, Action.APPROVAL_READ): True,
    (Role.OPERATOR, Action.APPROVAL_READ): True,
    (Role.REVIEWER, Action.APPROVAL_READ): True,
    (Role.VIEWER, Action.APPROVAL_READ): True,
    # approval.decide
    (Role.OWNER, Action.APPROVAL_DECIDE): True,
    (Role.ADMIN, Action.APPROVAL_DECIDE): True,
    (Role.OPERATOR, Action.APPROVAL_DECIDE): False,
    (Role.REVIEWER, Action.APPROVAL_DECIDE): True,
    (Role.VIEWER, Action.APPROVAL_DECIDE): False,
    # usage.read
    (Role.OWNER, Action.USAGE_READ): True,
    (Role.ADMIN, Action.USAGE_READ): True,
    (Role.OPERATOR, Action.USAGE_READ): True,
    (Role.REVIEWER, Action.USAGE_READ): False,
    (Role.VIEWER, Action.USAGE_READ): True,
    # audit.read
    (Role.OWNER, Action.AUDIT_READ): True,
    (Role.ADMIN, Action.AUDIT_READ): True,
    (Role.OPERATOR, Action.AUDIT_READ): False,
    (Role.REVIEWER, Action.AUDIT_READ): False,
    (Role.VIEWER, Action.AUDIT_READ): False,
}


@pytest.mark.parametrize("role_action, expected", EXPECTED_MATRIX.items())
def test_permission_matrix_exact_match(
    role_action: tuple[Role, Action],
    expected: bool,
) -> None:
    """P2-T25: Every role/action pair matches the specification matrix."""
    role, action = role_action
    assert has_permission(role, action) is expected


def test_approval_role_hierarchy() -> None:
    """Validate can_decide_approval obeys reviewer < admin < owner."""
    # Reviewer can decide reviewer-level, but not admin or owner
    assert can_decide_approval(Role.REVIEWER, Role.REVIEWER) is True
    assert can_decide_approval(Role.REVIEWER, Role.ADMIN) is False
    assert can_decide_approval(Role.REVIEWER, Role.OWNER) is False

    # Admin can decide reviewer- and admin-level, but not owner
    assert can_decide_approval(Role.ADMIN, Role.REVIEWER) is True
    assert can_decide_approval(Role.ADMIN, Role.ADMIN) is True
    assert can_decide_approval(Role.ADMIN, Role.OWNER) is False

    # Owner can decide any level
    assert can_decide_approval(Role.OWNER, Role.REVIEWER) is True
    assert can_decide_approval(Role.OWNER, Role.ADMIN) is True
    assert can_decide_approval(Role.OWNER, Role.OWNER) is True

    # Operator and viewer cannot decide any level
    assert can_decide_approval(Role.OPERATOR, Role.REVIEWER) is False
    assert can_decide_approval(Role.VIEWER, Role.REVIEWER) is False


def test_member_role_management_rules() -> None:
    """Validate member management privileges for admin vs owner."""
    # Owner can grant owner, change owner, manage anyone
    assert can_manage_member_role(Role.OWNER, None, Role.OWNER) is True
    assert can_manage_member_role(Role.OWNER, Role.OWNER, Role.ADMIN) is True
    assert can_manage_member_role(Role.OWNER, Role.ADMIN, Role.OPERATOR) is True

    # Admin cannot grant owner or touch owner
    assert can_manage_member_role(Role.ADMIN, None, Role.OWNER) is False
    assert can_manage_member_role(Role.ADMIN, Role.OWNER, Role.ADMIN) is False
    assert can_manage_member_role(Role.ADMIN, None, Role.ADMIN) is True
    assert can_manage_member_role(Role.ADMIN, Role.OPERATOR, Role.ADMIN) is True

    # Viewer/operator cannot manage roles
    assert can_manage_member_role(Role.VIEWER, None, Role.OPERATOR) is False
    assert can_manage_member_role(Role.OPERATOR, None, Role.OPERATOR) is False
