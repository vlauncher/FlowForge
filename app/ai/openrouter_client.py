"""OpenRouter client enforcing strict free-model compliance and rate limits."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import httpx

from app.ai.interface import (
    LLMClient,
    LLMProviderError,
    LLMRateLimitedError,
    LLMRequest,
    LLMResult,
    assert_free_model,
)
from app.ai.rate_limiter import SlidingWindowLimiter


class OpenRouterClient(LLMClient):
    """Production client for OpenRouter API constrained to :free models."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 30.0,
        rate_limiter: SlidingWindowLimiter | None = None,
        daily_usage_counter: Callable[[], Awaitable[int]] | None = None,
        daily_limit: int = 50,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.rate_limiter = rate_limiter or SlidingWindowLimiter(rpm=20, rpd=50)
        self.daily_usage_counter = daily_usage_counter
        self.daily_limit = daily_limit
        self._client = http_client

    async def generate_json(self, req: LLMRequest) -> LLMResult:
        # 1. Enforce strict free model policy
        assert_free_model(req.model)
        for fallback in req.fallback_models:
            assert_free_model(fallback)

        # 2. Daily DB usage check if counter provided
        if self.daily_usage_counter is not None:
            today_count = await self.daily_usage_counter()
            if today_count >= self.daily_limit:
                raise LLMRateLimitedError(
                    f"LLM_RATE_LIMITED: daily free tier quota of {self.daily_limit} calls exceeded"
                )

        # 3. Local sliding window rate limiter
        self.rate_limiter.acquire()

        # 4. Prepare OpenRouter payload
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://flowforge.dev",
            "X-Title": "FlowForge",
        }

        all_models = [req.model, *req.fallback_models]
        payload = {
            "model": req.model,
            "models": all_models,
            "messages": [
                {"role": "system", "content": req.system_prompt},
                {"role": "user", "content": req.user_prompt},
            ],
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "step_output",
                    "strict": True,
                    "schema": req.json_schema,
                },
            },
            "provider": {"allow_fallbacks": True},
        }

        start_time = time.monotonic()
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        should_close_client = self._client is None

        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            msg = f"OpenRouter request timed out after {self.timeout_seconds}s"
            raise LLMProviderError(msg) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(f"Network error communicating with OpenRouter: {exc}") from exc
        finally:
            if should_close_client:
                await client.aclose()

        latency_ms = int((time.monotonic() - start_time) * 1000)

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "30")
            raise LLMRateLimitedError(
                "LLM_RATE_LIMITED: OpenRouter free tier rate limit exceeded",
                headers={"Retry-After": retry_after},
            )

        if resp.status_code >= 400:
            raise LLMProviderError(
                f"OpenRouter returned error HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise LLMProviderError("Empty choices list in OpenRouter response")

            raw_text = choices[0].get("message", {}).get("content", "")
            model_used = data.get("model", req.model)
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
        except Exception as exc:
            if isinstance(exc, LLMProviderError):
                raise
            raise LLMProviderError(f"Malformed JSON response from OpenRouter: {exc}") from exc

        return LLMResult(
            model_used=model_used,
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            billed_cost_micro_usd=0,
        )
