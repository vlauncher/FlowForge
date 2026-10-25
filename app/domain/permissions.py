"""Role-Based Access Control (RBAC) permission matrix and evaluation rules."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Organization membership roles in order of privilege."""

    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Action(StrEnum):
    """Securable platform actions."""

    ORG_MANAGE = "org.manage"
    MEMBER_MANAGE = "member.manage"
    CREDENTIAL_MANAGE = "credential.manage"
    WORKFLOW_WRITE = "workflow.write"
    WORKFLOW_PUBLISH = "workflow.publish"
    WORKFLOW_READ = "workflow.read"
    RUN_TRIGGER = "run.trigger"
    RUN_CANCEL = "run.cancel"
    RUN_RETRY = "run.retry"
    RUN_READ = "run.read"
    APPROVAL_READ = "approval.read"
    APPROVAL_DECIDE = "approval.decide"
    USAGE_READ = "usage.read"
    AUDIT_READ = "audit.read"


# Exact permission matrix defined in spec/00-global.md §2
ROLE_PERMISSIONS: dict[Role, set[Action]] = {
    Role.OWNER: {
        Action.ORG_MANAGE,
        Action.MEMBER_MANAGE,
        Action.CREDENTIAL_MANAGE,
        Action.WORKFLOW_WRITE,
        Action.WORKFLOW_PUBLISH,
        Action.WORKFLOW_READ,
        Action.RUN_TRIGGER,
        Action.RUN_CANCEL,
        Action.RUN_RETRY,
        Action.RUN_READ,
        Action.APPROVAL_READ,
        Action.APPROVAL_DECIDE,
        Action.USAGE_READ,
        Action.AUDIT_READ,
    },
    Role.ADMIN: {
        Action.ORG_MANAGE,
        Action.MEMBER_MANAGE,
        Action.CREDENTIAL_MANAGE,
        Action.WORKFLOW_WRITE,
        Action.WORKFLOW_PUBLISH,
        Action.WORKFLOW_READ,
        Action.RUN_TRIGGER,
        Action.RUN_CANCEL,
        Action.RUN_RETRY,
        Action.RUN_READ,
        Action.APPROVAL_READ,
        Action.APPROVAL_DECIDE,
        Action.USAGE_READ,
        Action.AUDIT_READ,
    },
    Role.OPERATOR: {
        Action.WORKFLOW_READ,
        Action.RUN_TRIGGER,
        Action.RUN_CANCEL,
        Action.RUN_RETRY,
        Action.RUN_READ,
        Action.APPROVAL_READ,
        Action.USAGE_READ,
    },
    Role.REVIEWER: {
        Action.WORKFLOW_READ,
        Action.RUN_READ,
        Action.APPROVAL_READ,
        Action.APPROVAL_DECIDE,
    },
    Role.VIEWER: {
        Action.WORKFLOW_READ,
        Action.RUN_READ,
        Action.APPROVAL_READ,
        Action.USAGE_READ,
    },
}

# Approval role hierarchy ordering (reviewer < admin < owner)
APPROVAL_ROLE_LEVELS: dict[Role, int] = {
    Role.REVIEWER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}


def has_permission(role: Role | str, action: Action | str) -> bool:
    """Return True if the given role is granted the action."""
    try:
        r = Role(role)
        a = Action(action)
    except ValueError:
        return False
    return a in ROLE_PERMISSIONS.get(r, set())


def can_decide_approval(caller_role: Role | str, assigned_role: Role | str) -> bool:
    """Verify decider has approval.decide permission AND role >= assigned_role."""
    if not has_permission(caller_role, Action.APPROVAL_DECIDE):
        return False
    try:
        c_level = APPROVAL_ROLE_LEVELS.get(Role(caller_role), 0)
        a_level = APPROVAL_ROLE_LEVELS.get(Role(assigned_role), 0)
        return c_level >= a_level and a_level > 0
    except ValueError:
        return False


def can_manage_member_role(
    actor_role: Role | str,
    target_current_role: Role | str | None,
    new_role: Role | str,
) -> bool:
    """Check if actor is allowed to assign or alter target's role.

    Rules:
    1. Actor must have member.manage permission.
    2. Owner can manage any role (grant owner, demote owner).
    3. Admin CANNOT touch an owner and CANNOT grant owner.
    """
    if not has_permission(actor_role, Action.MEMBER_MANAGE):
        return False

    r_actor = Role(actor_role)
    r_new = Role(new_role)
    r_target = Role(target_current_role) if target_current_role else None

    if r_actor == Role.OWNER:
        return True

    if r_actor == Role.ADMIN:
        # Admin cannot grant owner role
        if r_new == Role.OWNER:
            return False
        # Admin cannot alter an existing owner
        if r_target == Role.OWNER:
            return False
        return True

    return False
