"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import kombu
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestIdMiddleware
from app.core.rate_limit import RateLimitMiddleware
from app.core.readiness import register_check
from app.infrastructure.db.session import get_session, get_session_factory
from app.observability.metrics import (
    PrometheusMetricsMiddleware,
    get_metrics_content,
    update_live_gauges,
)
from app.observability.tracing import setup_tracing


async def check_db_readiness() -> None:
    """Readiness probe checking database connectivity."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT 1"))


async def check_broker_readiness() -> None:
    """Readiness probe checking RabbitMQ broker connectivity."""
    settings = get_settings()

    def _probe() -> None:
        with kombu.Connection(settings.rabbitmq_url, connect_timeout=1.5) as conn:
            conn.connect()

    await asyncio.to_thread(_probe)


register_check("db", check_db_readiness)
register_check("broker", check_broker_readiness)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager for startup and shutdown events."""
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a new FlowForge FastAPI application instance."""
    cfg = settings or get_settings()

    configure_logging(cfg.log_level)

    docs_url = None if cfg.app_env == "prod" else "/docs"
    redoc_url = None if cfg.app_env == "prod" else "/redoc"
    openapi_url = None if cfg.app_env == "prod" else "/openapi.json"

    app = FastAPI(
        title="FlowForge API",
        version="0.1.0",
        description="AI Agent and Durable Workflow Automation Platform",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    # Global error handlers
    install_error_handlers(app)

    # Initialize OpenTelemetry distributed tracing
    setup_tracing(service_name=cfg.otel_service_name)

    # Include routers
    app.include_router(health_router)
    app.include_router(v1_router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(session: AsyncSession = Depends(get_session)) -> Response:
        await update_live_gauges(session)
        return Response(content=get_metrics_content(), media_type=CONTENT_TYPE_LATEST)

    # Middleware execution order (outermost to innermost):
    # RequestId -> CORS -> PrometheusMetrics -> BodySizeLimit -> Router
    # Starlette add_middleware wraps from inside out, so add innermost first.
    app.add_middleware(RateLimitMiddleware, enabled=cfg.rate_limit_enabled)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=cfg.max_request_bytes)
    if cfg.metrics_enabled:
        app.add_middleware(PrometheusMetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)

    return app
