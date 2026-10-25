"""Durable allowlisted HTTP tool adapter enforcing the tool_effects ledger protocol."""

from __future__ import annotations

import email.utils
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.errors import EgressBlockedError
from app.core.request_context import get_request_id
from app.domain.template_engine import build_scope, resolve_value
from app.domain.workflow_definition import canonical_json
from app.infrastructure.http_tool.circuit_breaker import circuit_breaker
from app.infrastructure.http_tool.egress import validate_and_pin_url
from app.modules.integrations.repository import IntegrationRepository
from app.observability.tracing import get_tracer

logger = logging.getLogger("flowforge.http_tool")

MAX_RESPONSE_BYTES = 65536  # 64 KB cap


@dataclass
class HttpStepResult:
    success: bool
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    retryable: bool = False
    retry_after: float | None = None


def parse_retry_after(header_val: str | None) -> float | None:
    """Parse Retry-After header as integer seconds or HTTP-date."""
    if not header_val:
        return None
    try:
        return float(header_val)
    except ValueError:
        pass
    try:
        parsed_tuple = email.utils.parsedate_tz(header_val)
        if parsed_tuple:
            timestamp = email.utils.mktime_tz(parsed_tuple)
            diff = timestamp - time.time()
            return max(0.0, diff)
    except Exception:
        pass
    return None


async def execute_http_step(
    step_def: dict[str, Any],
    run_id: UUID,
    org_id: UUID,
    inputs: dict[str, Any],
    context: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    client_override: httpx.AsyncClient | None = None,
) -> HttpStepResult:
    """Execute an HTTP tool step in accordance with the Phase 5 ledger protocol."""
    step_id = step_def["id"]
    cfg = step_def.get("config", {})
    scope = build_scope(inputs, context)

    # 1. Resolve URL and method
    raw_url = cfg.get("url", "")
    url = str(resolve_value(raw_url, scope))
    method = cfg.get("method", "GET").upper()
    timeout_secs = cfg.get("timeout_seconds", 10)
    effect = cfg.get("effect", "read" if method in ("GET", "HEAD") else "write")
    supports_idempotency = cfg.get("provider_supports_idempotency", True)

    parsed = urlparse(url)
    url_host = parsed.hostname or ""
    idempotency_key = f"{run_id}:{step_id}"

    # 2. Resolve Credential if configured
    credential_id_raw = cfg.get("credential_id")
    provider = url_host
    allowed_hosts = list(get_settings().egress_allowed_hosts)
    bearer_secret: str | None = None

    if credential_id_raw:
        async with session_factory() as session:
            repo = IntegrationRepository(session)
            cred = await repo.get_credential_by_id(UUID(str(credential_id_raw)), org_id=org_id)
            if not cred:
                return HttpStepResult(
                    success=False,
                    error_code="CREDENTIAL_NOT_FOUND",
                    error_detail=f"Credential '{credential_id_raw}' not found",
                    retryable=False,
                )
            provider = cred.provider
            allowed_hosts = cred.allowed_hosts
            bearer_secret = decrypt_secret(cred.encrypted_secret, cred.key_id)

    # 3. Pre-check Tool Effects Ledger (Transaction)
    async with session_factory() as session:
        async with session.begin():
            repo = IntegrationRepository(session)
            existing_effect = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
            if existing_effect:
                if existing_effect.state == "COMMITTED":
                    logger.info(
                        "Ledger COMMITTED hit for %s:%s. Replaying output.",
                        provider,
                        idempotency_key,
                    )
                    return HttpStepResult(
                        success=True,
                        output=existing_effect.response_summary or {},
                    )
                if existing_effect.state == "AMBIGUOUS" and not supports_idempotency:
                    logger.warning(
                        "Ledger AMBIGUOUS halt for non-idempotent %s:%s",
                        provider,
                        idempotency_key,
                    )
                    return HttpStepResult(
                        success=False,
                        error_code="TOOL_EFFECT_AMBIGUOUS",
                        error_detail=(
                            "Step previously timed out during write and provider does not"
                            " support idempotency"
                        ),
                        retryable=False,
                    )

    # 4. Allowlist & Egress check (DNS rebinding safe)
    pinned_url = url
    pinned_headers: dict[str, str] = {}
    pinned_extensions: dict[str, Any] = {}
    try:
        if client_override is not None:
            # Under test mock transport: validate scheme, port and allowlist without network DNS
            if parsed.scheme != "https" or url_host not in allowed_hosts:
                raise EgressBlockedError(f"Host '{url_host}' is blocked or not HTTPS")
        else:
            pinned_url, host_header, pinned_extensions = await validate_and_pin_url(
                url, allowed_hosts=allowed_hosts
            )
            pinned_headers["Host"] = host_header
    except EgressBlockedError as e:
        async with session_factory() as session:
            async with session.begin():
                repo = IntegrationRepository(session)
                await repo.upsert_tool_effect_intended(
                    org_id=org_id,
                    run_id=run_id,
                    step_id=step_id,
                    provider=provider,
                    idempotency_key=idempotency_key,
                    request_hash="blocked",
                )
                eff = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
                if eff:
                    eff.state = "FAILED"
        return HttpStepResult(
            success=False,
            error_code="EGRESS_BLOCKED",
            error_detail=str(e),
            retryable=False,
        )

    # 5. Circuit Breaker check
    if not circuit_breaker.can_execute(provider):
        return HttpStepResult(
            success=False,
            error_code="STEP_HTTP_ERROR",
            error_detail=f"Circuit breaker for provider '{provider}' is OPEN",
            retryable=True,
            retry_after=30.0,
        )

    # 6. Resolve headers & body
    raw_headers = cfg.get("headers", {})
    resolved_headers: dict[str, str] = {
        k: str(resolve_value(v, scope)) for k, v in raw_headers.items()
    }
    resolved_body = resolve_value(cfg.get("body"), scope) if cfg.get("body") is not None else None

    # Prepare request hash & safe headers
    request_data = {
        "method": method,
        "url": url,
        "headers": {k: v for k, v in resolved_headers.items() if k.lower() != "authorization"},
        "body": resolved_body,
    }
    request_hash = hashlib.sha256(canonical_json(request_data)).hexdigest()

    # 7. Record INTENDED state in ledger before socket connection
    async with session_factory() as session:
        async with session.begin():
            repo = IntegrationRepository(session)
            await repo.upsert_tool_effect_intended(
                org_id=org_id,
                run_id=run_id,
                step_id=step_id,
                provider=provider,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )

    # 8. Network Execution (outside DB transaction)
    req_headers = dict(resolved_headers)
    req_headers["Idempotency-Key"] = idempotency_key
    req_id = get_request_id() or str(run_id)
    req_headers["X-Request-ID"] = req_id
    if bearer_secret:
        req_headers["Authorization"] = f"Bearer {bearer_secret}"

    timeout = httpx.Timeout(timeout_secs, connect=5.0)

    try:

        async def _do_request(c: httpx.AsyncClient) -> httpx.Response:
            content = None
            json_body = None
            if resolved_body is not None:
                if isinstance(resolved_body, (dict, list)):
                    json_body = resolved_body
                else:
                    content = str(resolved_body).encode("utf-8")

            req_url = url if client_override else pinned_url
            final_headers = dict(req_headers)
            if not client_override:
                final_headers.update(pinned_headers)
            extensions = None if client_override else pinned_extensions

            return await c.request(
                method=method,
                url=req_url,
                headers=final_headers,
                json=json_body,
                content=content,
                timeout=timeout,
                extensions=extensions,
            )

        tracer = get_tracer()
        with tracer.start_as_current_span("worker.http_request") as span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.host", url_host)
            if client_override:
                response = await _do_request(client_override)
            else:
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    response = await _do_request(client)
            span.set_attribute("http.status_code", response.status_code)

        status_code = response.status_code
        resp_bytes = response.content[:MAX_RESPONSE_BYTES]

        parsed_json = None
        try:
            parsed_json = response.json()
        except Exception:
            parsed_json = {"raw": resp_bytes.decode("utf-8", errors="replace")}

        safe_resp_headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("set-cookie", "authorization")
        }
        summary = {
            "status": status_code,
            "body": parsed_json,
            "headers": safe_resp_headers,
        }

        # 9. Classify outcome
        if 200 <= status_code < 300:
            circuit_breaker.record_success(provider)
            external_ref = parsed_json.get("id") if isinstance(parsed_json, dict) else None

            async with session_factory() as session:
                async with session.begin():
                    repo = IntegrationRepository(session)
                    eff = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
                    if eff:
                        eff.state = "COMMITTED"
                        eff.external_ref = str(external_ref) if external_ref else None
                        eff.response_summary = summary

            return HttpStepResult(success=True, output=summary)

        # 429 or 502/503/504 -> retryable failure
        if status_code in (429, 502, 503, 504):
            circuit_breaker.record_failure(provider)
            retry_after = parse_retry_after(response.headers.get("Retry-After"))

            async with session_factory() as session:
                async with session.begin():
                    repo = IntegrationRepository(session)
                    eff = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
                    if eff:
                        eff.state = "FAILED"
                        eff.response_summary = summary

            return HttpStepResult(
                success=False,
                error_code="STEP_HTTP_ERROR",
                error_detail=f"Upstream returned HTTP {status_code}",
                retryable=True,
                retry_after=retry_after,
            )

        # Non-retryable 4xx
        async with session_factory() as session:
            async with session.begin():
                repo = IntegrationRepository(session)
                eff = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
                if eff:
                    eff.state = "FAILED"
                    eff.response_summary = summary

        return HttpStepResult(
            success=False,
            error_code="STEP_HTTP_ERROR",
            error_detail=f"Upstream returned non-retryable HTTP {status_code}",
            retryable=False,
        )

    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        circuit_breaker.record_failure(provider)
        async with session_factory() as session:
            async with session.begin():
                repo = IntegrationRepository(session)
                eff = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
                if eff:
                    eff.state = "FAILED"

        return HttpStepResult(
            success=False,
            error_code="STEP_CONNECT_ERROR",
            error_detail=f"Connection to {url_host} failed: {exc}",
            retryable=True,
        )

    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
        circuit_breaker.record_failure(provider)
        new_state = "AMBIGUOUS" if effect == "write" else "FAILED"

        async with session_factory() as session:
            async with session.begin():
                repo = IntegrationRepository(session)
                eff = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
                if eff:
                    eff.state = new_state

        if effect == "write" and not supports_idempotency:
            return HttpStepResult(
                success=False,
                error_code="TOOL_EFFECT_AMBIGUOUS",
                error_detail=(
                    "HTTP write request timed out and provider does not support idempotency"
                    " key replay"
                ),
                retryable=False,
            )

        return HttpStepResult(
            success=False,
            error_code="STEP_TIMEOUT",
            error_detail=f"Request to {url_host} timed out: {exc}",
            retryable=True,
        )

    except Exception as exc:
        circuit_breaker.record_failure(provider)
        async with session_factory() as session:
            async with session.begin():
                repo = IntegrationRepository(session)
                eff = await repo.get_tool_effect(provider, idempotency_key, org_id=org_id)
                if eff:
                    eff.state = "FAILED"

        return HttpStepResult(
            success=False,
            error_code="STEP_HTTP_ERROR",
            error_detail=str(exc),
            retryable=False,
        )
