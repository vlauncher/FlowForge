"""Operational health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.errors import problem_response
from app.core.readiness import run_checks

router = APIRouter(tags=["ops"])


@router.get("/health", summary="Liveness Probe")
async def health() -> dict[str, str]:
    """Check if the service process is alive."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness Probe")
async def ready(request: Request) -> JSONResponse:
    """Check if all downstream dependencies are healthy and ready to serve traffic."""
    checks = await run_checks()
    all_ok = all(status == "ok" for status in checks.values())

    if not all_ok:
        return problem_response(
            request,
            code="SERVICE_UNAVAILABLE",
            status=503,
            title="Service Unavailable",
            detail="One or more readiness checks failed.",
            errors=[{"check": name, "status": status} for name, status in checks.items()],
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ready", "checks": checks},
    )
