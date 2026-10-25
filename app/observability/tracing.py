"""Distributed tracing configuration and context propagation using OpenTelemetry (Phase 8)."""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.context.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.core.config import get_settings

_PROPAGATOR = TraceContextTextMapPropagator()
_GLOBAL_PROVIDER: TracerProvider | None = None


def setup_tracing(
    service_name: str | None = None,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Initialize OpenTelemetry TracerProvider and set global tracer."""
    global _GLOBAL_PROVIDER
    settings = get_settings()
    svc_name = service_name or settings.otel_service_name or "flowforge-api"

    if _GLOBAL_PROVIDER is None:
        resource = Resource.create({"service.name": svc_name})
        _GLOBAL_PROVIDER = TracerProvider(resource=resource)
        trace.set_tracer_provider(_GLOBAL_PROVIDER)

    if exporter is not None:
        _GLOBAL_PROVIDER.add_span_processor(SimpleSpanProcessor(exporter))

    return _GLOBAL_PROVIDER


def get_tracer(name: str = "flowforge") -> trace.Tracer:
    """Return a named OpenTelemetry tracer."""
    return trace.get_tracer(name)


def inject_trace_context(
    carrier: dict[str, str] | None = None,
    context: Context | None = None,
) -> dict[str, str]:
    """Inject current or given trace context into carrier dict via W3C TraceContext."""
    if carrier is None:
        carrier = {}
    _PROPAGATOR.inject(carrier, context=context)
    return carrier


def extract_trace_context(carrier: dict[str, Any] | None) -> Context:
    """Extract W3C trace context from carrier dict."""
    if not carrier:
        from opentelemetry import context as otel_context

        return otel_context.get_current()
    # Ensure string values for text map propagator
    str_carrier = {str(k): str(v) for k, v in carrier.items()}
    return _PROPAGATOR.extract(str_carrier)
