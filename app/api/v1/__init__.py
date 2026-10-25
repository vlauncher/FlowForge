"""FlowForge API v1 Router aggregating all domain sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.approvals.router import router as approvals_router
from app.modules.audit.router import router as audit_router
from app.modules.executions.router import router as executions_router
from app.modules.identity.router import router as identity_router
from app.modules.integrations.router import router as integrations_router
from app.modules.organizations.router import router as organizations_router
from app.modules.triggers.router import router as triggers_router
from app.modules.usage.router import router as usage_router
from app.modules.workflows.router import router as workflows_router

router = APIRouter(prefix="/v1")
router.include_router(identity_router)
router.include_router(organizations_router)
router.include_router(workflows_router)
router.include_router(executions_router)
router.include_router(integrations_router)
router.include_router(approvals_router)
router.include_router(audit_router)
router.include_router(usage_router)
router.include_router(triggers_router)
