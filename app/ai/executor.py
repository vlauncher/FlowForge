"""Execution engine for AI workflow steps (llm_classify, llm_transform)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.fake_client import FakeLLM
from app.ai.interface import (
    InvalidLLMOutputError,
    LLMClient,
    LLMNonFreeModelError,
    LLMRateLimitedError,
    LLMRequest,
    assert_free_model,
)
from app.ai.openrouter_client import OpenRouterClient
from app.ai.prompts.loader import get_prompt_template
from app.ai.rate_limiter import SlidingWindowLimiter
from app.ai.validator import parse_and_validate_json
from app.core.config import Settings, get_settings
from app.domain.template_engine import TemplateResolutionError, build_scope, resolve_value
from app.modules.usage.repository import UsageRepository
from app.observability.metrics import LLM_REQUESTS_TOTAL, LLM_TOKENS_TOTAL
from app.observability.tracing import get_tracer

logger = logging.getLogger("flowforge.ai.executor")


@dataclass
class AIStepResult:
    """Outcome of an AI step execution."""

    success: bool
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    retryable: bool = False


async def _persist_usage(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: UUID,
    run_id: UUID,
    step_id: str,
    attempt_id: UUID | None,
    provider: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    estimated_cost_micro_usd: int,
    billed_cost_micro_usd: int,
    latency_ms: int,
    prompt_template_id: str,
    prompt_template_version: int,
    outcome: str,
) -> None:
    """Write an immutable usage record in an isolated transaction."""
    try:
        async with session_factory() as session:
            async with session.begin():
                repo = UsageRepository(session)
                await repo.record_usage(
                    org_id=org_id,
                    run_id=run_id,
                    step_id=step_id,
                    attempt_id=attempt_id,
                    provider=provider,
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    estimated_cost_micro_usd=estimated_cost_micro_usd,
                    billed_cost_micro_usd=billed_cost_micro_usd,
                    latency_ms=latency_ms,
                    prompt_template_id=prompt_template_id,
                    prompt_template_version=prompt_template_version,
                    outcome=outcome,
                )
    except Exception as exc:
        logger.error("Failed to persist usage record for run %s step %s: %s", run_id, step_id, exc)


async def execute_ai_step(
    *,
    step_def: dict[str, Any],
    run_id: UUID,
    org_id: UUID,
    attempt_id: UUID | None,
    inputs: dict[str, Any],
    context: dict[str, Any],
    session_factory: async_sessionmaker[AsyncSession],
    client_override: LLMClient | None = None,
    settings_override: Settings | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> AIStepResult:
    """Execute llm_classify or llm_transform step with bounded repair retries."""
    settings = settings_override or get_settings()
    step_id = step_def.get("id", "ai_step")
    step_type = step_def.get("type", "unknown")
    cfg = step_def.get("config", {})

    # 1. Resolve prompt template
    template_id = cfg.get("prompt_template_id", "")
    try:
        template = get_prompt_template(template_id)
    except KeyError:
        return AIStepResult(
            success=False,
            error_code="INVALID_STEP_CONFIG",
            error_detail=f"Prompt template '{template_id}' not found",
            retryable=False,
        )

    # 2. Template resolution for input string
    raw_input = cfg.get("input", "")
    try:
        scope = build_scope(inputs, context)
        resolved_input = str(resolve_value(raw_input, scope))
    except TemplateResolutionError as exc:
        return AIStepResult(
            success=False,
            error_code="TEMPLATE_RESOLUTION_ERROR",
            error_detail=str(exc),
            retryable=False,
        )

    # 3. Build prompts and JSON Schema
    system_prompt = template.format_system()
    if step_type == "llm_classify":
        labels = cfg.get("labels", [])
        user_prompt = template.format_user(resolved_input, labels=labels)
        json_schema = {
            "type": "object",
            "required": ["label", "confidence"],
            "properties": {
                "label": {"type": "string", "enum": labels},
                "confidence": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
            },
            "additionalProperties": False,
        }
        max_tokens = int(cfg.get("max_tokens") or 100)
    elif step_type == "llm_transform":
        user_prompt = template.format_user(resolved_input)
        json_schema = cfg.get("output_schema", {})
        max_tokens = int(cfg.get("max_tokens") or 400)
    else:
        return AIStepResult(
            success=False,
            error_code="INVALID_STEP_CONFIG",
            error_detail=f"Unsupported AI step type: {step_type}",
            retryable=False,
        )

    # 4. Resolve client
    if client_override is not None:
        client = client_override
        provider_name = "fake" if isinstance(client_override, FakeLLM) else "openrouter"
    elif settings.llm_provider == "openrouter":
        provider_name = "openrouter"
        limiter = SlidingWindowLimiter(rpm=settings.llm_free_rpm, rpd=settings.llm_free_rpd)
        client = OpenRouterClient(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            rate_limiter=limiter,
            daily_limit=settings.llm_free_rpd,
            http_client=http_client,
        )
    else:
        provider_name = "fake"
        client = FakeLLM()

    model_name = settings.llm_model
    fallback_models = settings.llm_fallback_models

    # Free model enforcement check
    try:
        assert_free_model(model_name)
        for fb in fallback_models:
            assert_free_model(fb)
    except LLMNonFreeModelError as exc:
        return AIStepResult(
            success=False,
            error_code="LLM_NON_FREE_MODEL",
            error_detail=str(exc),
            retryable=False,
        )

    req = LLMRequest(
        model=model_name,
        fallback_models=fallback_models,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_schema=json_schema,
        max_tokens=max_tokens,
    )

    # 5. Bounded repair loop (max 2 attempts per step execution)
    last_error_detail = ""
    tracer = get_tracer()
    for attempt_idx in range(1, 3):
        try:
            with tracer.start_as_current_span("worker.llm_call") as span:
                span.set_attribute("llm.provider", provider_name)
                span.set_attribute("llm.model", req.model)
                llm_res = await client.generate_json(req)
                span.set_attribute("llm.prompt_tokens", llm_res.prompt_tokens)
                span.set_attribute("llm.completion_tokens", llm_res.completion_tokens)
        except LLMRateLimitedError as exc:
            await _persist_usage(
                session_factory,
                org_id=org_id,
                run_id=run_id,
                step_id=step_id,
                attempt_id=attempt_id,
                provider=provider_name,
                model_name=model_name,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                estimated_cost_micro_usd=0,
                billed_cost_micro_usd=0,
                latency_ms=0,
                prompt_template_id=template.id,
                prompt_template_version=template.version,
                outcome="rate_limited",
            )
            return AIStepResult(
                success=False,
                error_code="LLM_RATE_LIMITED",
                error_detail=str(exc),
                retryable=False,
            )
        except LLMNonFreeModelError as exc:
            return AIStepResult(
                success=False,
                error_code="LLM_NON_FREE_MODEL",
                error_detail=str(exc),
                retryable=False,
            )
        except Exception as exc:
            await _persist_usage(
                session_factory,
                org_id=org_id,
                run_id=run_id,
                step_id=step_id,
                attempt_id=attempt_id,
                provider=provider_name,
                model_name=model_name,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                estimated_cost_micro_usd=0,
                billed_cost_micro_usd=0,
                latency_ms=0,
                prompt_template_id=template.id,
                prompt_template_version=template.version,
                outcome="provider_error",
            )
            return AIStepResult(
                success=False,
                error_code="LLM_PROVIDER_ERROR",
                error_detail=str(exc),
                retryable=False,
            )

        # Compute cost estimation
        estimated_cost = (llm_res.total_tokens * settings.llm_price_per_1k_tokens_micro_usd) // 1000

        # Validate structured output
        try:
            parsed_data = parse_and_validate_json(llm_res.raw_text, json_schema)
            # Record OK usage
            LLM_REQUESTS_TOTAL.labels(
                provider=provider_name, model=llm_res.model_used, outcome="ok"
            ).inc()
            LLM_TOKENS_TOTAL.labels(
                provider=provider_name, model=llm_res.model_used, token_type="prompt"
            ).inc(llm_res.prompt_tokens)
            LLM_TOKENS_TOTAL.labels(
                provider=provider_name, model=llm_res.model_used, token_type="completion"
            ).inc(llm_res.completion_tokens)

            await _persist_usage(
                session_factory,
                org_id=org_id,
                run_id=run_id,
                step_id=step_id,
                attempt_id=attempt_id,
                provider=provider_name,
                model_name=llm_res.model_used,
                prompt_tokens=llm_res.prompt_tokens,
                completion_tokens=llm_res.completion_tokens,
                total_tokens=llm_res.total_tokens,
                estimated_cost_micro_usd=estimated_cost,
                billed_cost_micro_usd=llm_res.billed_cost_micro_usd,
                latency_ms=llm_res.latency_ms,
                prompt_template_id=template.id,
                prompt_template_version=template.version,
                outcome="ok",
            )
            return AIStepResult(success=True, output=parsed_data)
        except InvalidLLMOutputError as exc:
            last_error_detail = str(exc)
            # Record invalid_output usage
            LLM_REQUESTS_TOTAL.labels(
                provider=provider_name, model=llm_res.model_used, outcome="invalid_output"
            ).inc()
            LLM_TOKENS_TOTAL.labels(
                provider=provider_name, model=llm_res.model_used, token_type="prompt"
            ).inc(llm_res.prompt_tokens)
            LLM_TOKENS_TOTAL.labels(
                provider=provider_name, model=llm_res.model_used, token_type="completion"
            ).inc(llm_res.completion_tokens)

            await _persist_usage(
                session_factory,
                org_id=org_id,
                run_id=run_id,
                step_id=step_id,
                attempt_id=attempt_id,
                provider=provider_name,
                model_name=llm_res.model_used,
                prompt_tokens=llm_res.prompt_tokens,
                completion_tokens=llm_res.completion_tokens,
                total_tokens=llm_res.total_tokens,
                estimated_cost_micro_usd=estimated_cost,
                billed_cost_micro_usd=llm_res.billed_cost_micro_usd,
                latency_ms=llm_res.latency_ms,
                prompt_template_id=template.id,
                prompt_template_version=template.version,
                outcome="invalid_output",
            )
            if attempt_idx < 2:
                logger.info(
                    "AI output failed schema validation on attempt 1, retrying: %s",
                    last_error_detail,
                )
                continue

    return AIStepResult(
        success=False,
        error_code="LLM_INVALID_OUTPUT",
        error_detail=f"Schema validation failed after 2 attempts: {last_error_detail}",
        retryable=False,
    )
