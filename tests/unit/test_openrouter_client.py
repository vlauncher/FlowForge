"""Unit tests for OpenRouterClient transport, authorization, and rate limit handling (P6-T04, P6-T05)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.interface import (
    LLMNonFreeModelError,
    LLMRateLimitedError,
    LLMRequest,
)
from app.ai.openrouter_client import OpenRouterClient


@pytest.mark.asyncio
async def test_openrouter_client_sends_bearer_and_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P6-T04: Verify client sends Bearer token, response_format with json_schema, and free models."""
    captured_requests: list[httpx.Request] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        body = json.loads(request.content.decode("utf-8"))

        assert request.headers["Authorization"] == "Bearer test-sk-openrouter"
        assert request.headers["Content-Type"] == "application/json"
        assert body["model"] == "openrouter/free"
        assert body["models"] == ["openrouter/free", "meta-llama/llama-3.3-70b-instruct:free"]
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True

        resp_payload = {
            "id": "gen-123",
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"label": "billing", "confidence": 0.95}',
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 15,
                "total_tokens": 57,
            },
        }
        return httpx.Response(200, json=resp_payload)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        openrouter = OpenRouterClient(
            api_key="test-sk-openrouter",
            http_client=client,
        )

        req = LLMRequest(
            model="openrouter/free",
            fallback_models=["meta-llama/llama-3.3-70b-instruct:free"],
            system_prompt="Classify ticket.",
            user_prompt="Ticket body.",
            json_schema={"type": "object", "properties": {"label": {"type": "string"}}},
            max_tokens=100,
        )

        result = await openrouter.generate_json(req)
        assert result.model_used == "meta-llama/llama-3.3-70b-instruct:free"
        assert result.raw_text == '{"label": "billing", "confidence": 0.95}'
        assert result.prompt_tokens == 42
        assert result.completion_tokens == 15
        assert result.total_tokens == 57
        assert result.billed_cost_micro_usd == 0

    assert len(captured_requests) == 1


@pytest.mark.asyncio
async def test_openrouter_client_handles_429_rate_limit() -> None:
    """P6-T04: OpenRouter returning 429 raises LLMRateLimitedError with Retry-After."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "45"}, text="Rate limit exceeded")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        openrouter = OpenRouterClient(
            api_key="test-sk-openrouter",
            http_client=client,
        )

        req = LLMRequest(
            model="openrouter/free",
            fallback_models=[],
            system_prompt="Sys",
            user_prompt="User",
            json_schema={},
            max_tokens=50,
        )

        with pytest.raises(LLMRateLimitedError) as exc_info:
            await openrouter.generate_json(req)
        assert exc_info.value.code == "LLM_RATE_LIMITED"
        assert exc_info.value.headers == {"Retry-After": "45"}


@pytest.mark.asyncio
async def test_openrouter_client_rejects_paid_model_before_network() -> None:
    """P6-T04: OpenRouterClient enforces assert_free_model before firing network request."""
    network_called = False

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_called
        network_called = True
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        openrouter = OpenRouterClient(
            api_key="test-sk-openrouter",
            http_client=client,
        )

        req = LLMRequest(
            model="openai/gpt-4o",
            fallback_models=[],
            system_prompt="Sys",
            user_prompt="User",
            json_schema={},
            max_tokens=50,
        )

        with pytest.raises(LLMNonFreeModelError):
            await openrouter.generate_json(req)

        assert not network_called


@pytest.mark.asyncio
async def test_openrouter_client_blocks_when_daily_quota_reached() -> None:
    """P6-T05: When today's count reaches daily_limit, call is blocked before network."""
    network_called = False

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_called
        network_called = True
        return httpx.Response(200, json={})

    async def mock_counter() -> int:
        return 50  # Daily limit reached

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        openrouter = OpenRouterClient(
            api_key="test-sk-openrouter",
            daily_usage_counter=mock_counter,
            daily_limit=50,
            http_client=client,
        )

        req = LLMRequest(
            model="openrouter/free",
            fallback_models=[],
            system_prompt="Sys",
            user_prompt="User",
            json_schema={},
            max_tokens=50,
        )

        with pytest.raises(LLMRateLimitedError) as exc_info:
            await openrouter.generate_json(req)

        assert exc_info.value.code == "LLM_RATE_LIMITED"
        assert not network_called
