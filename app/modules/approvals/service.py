"""Business logic service for human approval gate administration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ForbiddenError,
    InvalidStateTransitionError,
    NotFoundError,
)
from app.domain.permissions import can_decide_approval
from app.modules.approvals.repository import ApprovalRepository
from app.modules.approvals.schemas import (
    ApprovalDecisionRequest,
    ApprovalOut,
    ApprovalsPageResponse,
)
from app.modules.audit.repository import AuditRepository
from app.modules.executions.models import OutboxEvent


class ApprovalService:
    """Service orchestrating approval listings, inspections, and race-safe decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ApprovalRepository(session)
        self.audit_repo = AuditRepository(session)

    async def list_approvals(
        self,
        *,
        org_id: UUID,
        state: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ApprovalsPageResponse:
        """List approval requests for an organization."""
        items, next_cursor = await self.repo.list_approvals(
            org_id=org_id,
            state=state,
            limit=limit,
            cursor=cursor,
        )
        return ApprovalsPageResponse(
            items=[ApprovalOut.model_validate(it) for it in items],
            next_cursor=next_cursor,
        )

    async def get_approval(
        self,
        approval_id: UUID,
        *,
        user_id: UUID,
    ) -> ApprovalOut:
        """Get an approval request asserting caller membership."""
        res = await self.repo.get_by_id_with_membership(approval_id, user_id=user_id)
        if not res:
            raise NotFoundError("Approval request not found")
        approval, _ = res
        return ApprovalOut.model_validate(approval)

    async def decide_approval(
        self,
        approval_id: UUID,
        *,
        user_id: UUID,
        req: ApprovalDecisionRequest,
    ) -> ApprovalOut:
        """Race-safely decide a pending approval request and advance or fail the workflow run."""
        res = await self.repo.get_by_id_with_membership(approval_id, user_id=user_id)
        if not res:
            raise NotFoundError("Approval request not found")
        approval, caller_role = res

        # 1. Decision-time RBAC check (reviewer < admin < owner)
        if not can_decide_approval(caller_role, approval.assigned_role):
            raise ForbiddenError(
                f"Role '{caller_role}' lacks permission to decide approval "
                f"assigned to '{approval.assigned_role}'"
            )

        new_state = "APPROVED" if req.decision == "approve" else "REJECTED"

        # 2. Atomic conditional UPDATE on approval_requests
        decided = await self.repo.decide_approval_atomic(
            org_id=approval.org_id,
            approval_id=approval_id,
            new_state=new_state,
            decided_by=user_id,
            comment=req.comment,
        )

        if not decided:
            # Re-read to explain failure
            refreshed = await self.repo.get_by_id(approval_id, org_id=approval.org_id)
            if not refreshed:
                raise NotFoundError("Approval request not found")

            now_utc = datetime.now(UTC)
            if refreshed.expires_at <= now_utc:
                if refreshed.state == "PENDING":
                    refreshed.state = "EXPIRED"
                    await self.session.execute(
                        text("""
                            UPDATE workflow_runs
                            SET state = 'FAILED',
                                error_code = 'APPROVAL_EXPIRED',
                                error_detail = 'Approval request expired before decision',
                                finished_at = now(),
                                updated_at = now()
                            WHERE id = :run_id AND state = 'WAITING_APPROVAL'
                        """),
                        {"run_id": refreshed.run_id},
                    )
                    await self.session.commit()
                raise InvalidStateTransitionError("Approval request has expired")

            raise InvalidStateTransitionError(
                f"Approval request cannot be decided in state '{refreshed.state}'"
            )

        run_id, step_id, version_id = decided

        # 3. Synchronously transition workflow run and write audit event
        if req.decision == "approve":
            r5_stmt = text("""
                UPDATE workflow_runs
                SET state = 'QUEUED',
                    next_attempt_at = now(),
                    updated_at = now()
                WHERE id = :run_id
                  AND version_id = :version_id
                  AND state = 'WAITING_APPROVAL';
            """)
            r5_res = await self.session.execute(
                r5_stmt,
                {"run_id": run_id, "version_id": version_id},
            )
            if getattr(r5_res, "rowcount", 0) != 1:
                raise InvalidStateTransitionError("Run is not in WAITING_APPROVAL state")

            outbox = OutboxEvent(
                aggregate_type="run",
                aggregate_id=run_id,
                event_type="RunResumeRequested",
                schema_version=1,
                payload={"run_id": str(run_id), "org_id": str(approval.org_id)},
            )
            self.session.add(outbox)

            await self.audit_repo.record_audit_event(
                org_id=approval.org_id,
                actor_user_id=user_id,
                actor_type="user",
                action="approval.approved",
                target_type="approval_request",
                target_id=approval_id,
                metadata={"run_id": str(run_id), "step_id": step_id, "comment": req.comment},
            )
        else:
            r8_stmt = text("""
                UPDATE workflow_runs
                SET state = 'FAILED',
                    error_code = 'APPROVAL_REJECTED',
                    error_detail = 'Rejected by reviewer',
                    finished_at = now(),
                    updated_at = now()
                WHERE id = :run_id
                  AND state = 'WAITING_APPROVAL';
            """)
            await self.session.execute(r8_stmt, {"run_id": run_id})

            await self.audit_repo.record_audit_event(
                org_id=approval.org_id,
                actor_user_id=user_id,
                actor_type="user",
                action="approval.rejected",
                target_type="approval_request",
                target_id=approval_id,
                metadata={"run_id": str(run_id), "step_id": step_id, "comment": req.comment},
            )

        await self.session.commit()
        await self.session.refresh(approval)
        return ApprovalOut.model_validate(approval)
