"""Service logic for webhook triggers and signed HMAC verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.errors import (
    ForbiddenError,
    NotFoundError,
    ValidationError,
    WebhookReplayError,
    WebhookSignatureInvalidError,
)
from app.domain.permissions import Action, has_permission
from app.domain.workflow_definition import canonical_json
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.schemas import RunResponse, TriggerRunRequest
from app.modules.executions.service import ExecutionService
from app.modules.integrations.repository import IntegrationRepository
from app.modules.triggers.repository import TriggerRepository
from app.modules.triggers.schemas import CreateTriggerRequest, TriggerOut
from app.modules.workflows.repository import WorkflowRepository

logger = logging.getLogger("flowforge.triggers")


class TriggerService:
    """Handles webhook trigger management and HMAC-SHA256 signature verification."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.trigger_repo = TriggerRepository(session)
        self.workflow_repo = WorkflowRepository(session)
        self.integration_repo = IntegrationRepository(session)
        self.execution_repo = ExecutionRepository(session)

    async def create_trigger(
        self,
        workflow_id: UUID,
        req: CreateTriggerRequest,
        *,
        user_id: UUID,
    ) -> TriggerOut:
        """Create a webhook trigger for a workflow with tenant isolation."""
        workflow_and_role = await self.workflow_repo.get_by_id_for_user(
            workflow_id, user_id=user_id
        )
        if not workflow_and_role:
            raise NotFoundError(f"Workflow '{workflow_id}' not found")
        workflow, caller_role = workflow_and_role

        if not has_permission(caller_role, Action.WORKFLOW_WRITE):
            raise ForbiddenError(f"Role '{caller_role}' lacks permission '{Action.WORKFLOW_WRITE}'")

        org_id = workflow.org_id

        # Verify credential belongs to the same org
        credential = await self.integration_repo.get_credential_by_id(
            req.credential_id, org_id=org_id
        )
        if not credential:
            raise NotFoundError(f"Credential '{req.credential_id}' not found")

        trigger = await self.trigger_repo.create_trigger(
            workflow_id=workflow_id,
            credential_id=req.credential_id,
            org_id=org_id,
            kind="webhook",
        )
        await self.session.commit()

        return TriggerOut(
            id=trigger.id,
            workflow_id=trigger.workflow_id,
            credential_id=trigger.credential_id,
            enabled=trigger.enabled,
            webhook_url=f"/v1/triggers/webhooks/{trigger.id}",
            created_at=trigger.created_at,
        )

    async def list_triggers(
        self,
        workflow_id: UUID,
        *,
        user_id: UUID,
    ) -> list[TriggerOut]:
        """List triggers for a workflow."""
        workflow_and_role = await self.workflow_repo.get_by_id_for_user(
            workflow_id, user_id=user_id
        )
        if not workflow_and_role:
            raise NotFoundError(f"Workflow '{workflow_id}' not found")
        workflow, caller_role = workflow_and_role

        if not has_permission(caller_role, Action.WORKFLOW_READ):
            raise ForbiddenError(f"Role '{caller_role}' lacks permission '{Action.WORKFLOW_READ}'")

        triggers = await self.trigger_repo.list_by_workflow(workflow_id, org_id=workflow.org_id)
        return [
            TriggerOut(
                id=t.id,
                workflow_id=t.workflow_id,
                credential_id=t.credential_id,
                enabled=t.enabled,
                webhook_url=f"/v1/triggers/webhooks/{t.id}",
                created_at=t.created_at,
            )
            for t in triggers
        ]

    async def process_webhook(
        self,
        trigger_id: UUID,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> tuple[RunResponse, bool]:
        """Validate HMAC-SHA256 signature, verify replay window, and trigger execution."""
        # 1. Load active trigger with credential
        trigger_and_cred = await self.trigger_repo.get_active_trigger_with_credential(trigger_id)
        if not trigger_and_cred:
            raise NotFoundError(f"Webhook trigger '{trigger_id}' not found or inactive")
        trigger, credential = trigger_and_cred

        # 2. Extract and validate headers
        ts_header = headers.get("x-flowforge-timestamp") or headers.get("X-FlowForge-Timestamp")
        sig_header = headers.get("x-flowforge-signature") or headers.get("X-FlowForge-Signature")

        if not ts_header or not sig_header:
            raise WebhookSignatureInvalidError(
                "Missing required X-FlowForge-Timestamp or X-FlowForge-Signature header"
            )

        try:
            timestamp = int(ts_header)
        except ValueError as err:
            raise WebhookSignatureInvalidError("Malformed X-FlowForge-Timestamp header") from err

        settings = get_settings()
        tolerance = settings.webhook_timestamp_tolerance_seconds
        now_epoch = int(time.time())

        diff = abs(now_epoch - timestamp)
        if diff > tolerance:
            raise WebhookReplayError(
                f"Webhook timestamp outside tolerance window ({diff}s > {tolerance}s)"
            )

        # 3. Decrypt secret and verify HMAC-SHA256
        secret_plaintext = decrypt_secret(credential.encrypted_secret, credential.key_id)
        expected_mac = hmac.new(
            secret_plaintext.encode("utf-8"),
            f"{timestamp}.".encode() + raw_body,
            hashlib.sha256,
        ).hexdigest()
        expected_sig = f"v1={expected_mac}"

        if not hmac.compare_digest(expected_sig, sig_header):
            raise WebhookSignatureInvalidError("Webhook HMAC signature verification failed")

        # 4. Parse request body
        inputs: dict[str, Any] = {}
        if raw_body:
            try:
                body_json = json.loads(raw_body.decode("utf-8"))
                if isinstance(body_json, dict):
                    if "inputs" in body_json and isinstance(body_json["inputs"], dict):
                        inputs = body_json["inputs"]
                    else:
                        inputs = body_json
            except Exception as e:
                raise ValidationError(f"Invalid JSON payload in webhook body: {e}") from e

        # 5. Replay deduplication check
        idempotency_key = f"webhook:{trigger_id}:{sig_header}"
        existing = await self.execution_repo.get_run_by_idempotency_key(
            idempotency_key, org_id=trigger.org_id
        )

        if existing:
            existing_run, version_num = existing
            payload_to_fingerprint = {
                "version_id": str(existing_run.version_id),
                "inputs": inputs,
            }
            computed_fp = hashlib.sha256(canonical_json(payload_to_fingerprint)).hexdigest()
            age_seconds = (datetime.now(UTC) - existing_run.created_at).total_seconds()

            if existing_run.request_fingerprint == computed_fp and age_seconds <= tolerance:
                response = RunResponse(
                    run_id=existing_run.id,
                    state=existing_run.state,
                    workflow_id=existing_run.workflow_id,
                    workflow_version=version_num,
                    version_id=existing_run.version_id,
                    status_url=f"/v1/runs/{existing_run.id}",
                    created_at=existing_run.created_at,
                )
                return response, True
            else:
                raise WebhookReplayError("Webhook signature already consumed or expired")

        # 6. Trigger run via ExecutionService
        exec_service = ExecutionService(self.session)
        run_response, is_replayed = await exec_service.trigger_run(
            workflow_id=trigger.workflow_id,
            req=TriggerRunRequest(inputs=inputs),
            trigger_kind="webhook",
            trigger_id=trigger.id,
            org_id=trigger.org_id,
            idempotency_key=idempotency_key,
        )
        return run_response, is_replayed
