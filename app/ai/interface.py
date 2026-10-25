"""LLM Client interface, dataclasses, and exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.errors import AppError


class LLMError(AppError):
    """Base exception for all AI/LLM operations."""

    pass


class LLMNonFreeModelError(LLMError):
    """Raised when an unauthorized non-free model ID is specified."""

    def __init__(
        self,
        detail: str = "LLM_NON_FREE_MODEL: only :free models or openrouter/free are allowed",
    ) -> None:
        super().__init__(
            code="LLM_NON_FREE_MODEL",
            status=400,
            title="Non-Free Model Forbidden",
            detail=detail,
        )


class LLMRateLimitedError(LLMError):
    """Raised when rate limit or daily quota is exceeded."""

    def __init__(
        self,
        detail: str = "LLM rate limit reached",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            code="LLM_RATE_LIMITED",
            status=429,
            title="LLM Rate Limited",
            detail=detail,
            headers=headers,
        )


class LLMProviderError(LLMError):
    """Raised when LLM provider returns an unexpected upstream error."""

    def __init__(self, detail: str = "LLM provider communication error") -> None:
        super().__init__(
            code="LLM_PROVIDER_ERROR",
            status=502,
            title="LLM Provider Error",
            detail=detail,
        )


class InvalidLLMOutputError(LLMError):
    """Raised when LLM output does not conform to the expected JSON schema."""

    def __init__(
        self,
        detail: str = "LLM output did not conform to schema",
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            code="LLM_INVALID_OUTPUT",
            status=422,
            title="Invalid LLM Output",
            detail=detail,
            errors=errors,
        )


def assert_free_model(model: str) -> None:
    """Enforce that model name ends with :free or equals openrouter/free."""
    if model != "openrouter/free" and not model.endswith(":free"):
        raise LLMNonFreeModelError(
            f"LLM_NON_FREE_MODEL: model '{model}' is not a permitted free model"
        )


@dataclass(frozen=True)
class LLMRequest:
    model: str
    fallback_models: list[str]
    system_prompt: str
    user_prompt: str
    json_schema: dict[str, Any]
    max_tokens: int
    temperature: float = 0.0


@dataclass(frozen=True)
class LLMResult:
    model_used: str
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    billed_cost_micro_usd: int = 0


class LLMClient(Protocol):
    async def generate_json(self, req: LLMRequest) -> LLMResult: ...
