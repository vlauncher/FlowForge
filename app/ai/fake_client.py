"""Deterministic FakeLLM client for testing and local simulation."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import orjson

from app.ai.interface import (
    LLMClient,
    LLMRequest,
    LLMResult,
    assert_free_model,
)


class FakeLLM(LLMClient):
    """Deterministic mock implementation of LLMClient protocol."""

    def __init__(
        self,
        *,
        allow_non_free: bool = False,
        default_latency_ms: int = 25,
    ) -> None:
        self.allow_non_free = allow_non_free
        self.default_latency_ms = default_latency_ms
        self.calls: list[LLMRequest] = []
        self._queue: list[Any] = []
        self._custom_handler: Callable[[LLMRequest], str | dict[str, Any]] | None = None

    def queue_response(self, response: str | dict[str, Any] | Exception) -> None:
        """Enqueue a scripted response or exception to be yielded on next generate_json call."""
        self._queue.append(response)

    def set_handler(self, handler: Callable[[LLMRequest], str | dict[str, Any]]) -> None:
        """Set a custom handler callback for dynamic responses."""
        self._custom_handler = handler

    async def generate_json(self, req: LLMRequest) -> LLMResult:
        self.calls.append(req)

        if not self.allow_non_free:
            assert_free_model(req.model)
            for fallback in req.fallback_models:
                assert_free_model(fallback)

        if self._queue:
            item = self._queue.pop(0)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, dict):
                raw_text = orjson.dumps(item).decode("utf-8")
            else:
                raw_text = str(item)
        elif self._custom_handler is not None:
            resp = self._custom_handler(req)
            if isinstance(resp, dict):
                raw_text = orjson.dumps(resp).decode("utf-8")
            else:
                raw_text = str(resp)
        else:
            # Generate a sensible default based on the schema
            props = req.json_schema.get("properties", {})
            if "label" in props and "confidence" in props:
                labels = props["label"].get("enum", ["billing", "bug", "other"])
                default_obj = {"label": labels[0] if labels else "other", "confidence": 0.95}
            else:
                # Minimal mock object
                default_obj = dict.fromkeys(props.keys(), "test_val")
            raw_text = json.dumps(default_obj)

        prompt_tokens = max(10, len(req.user_prompt.split()) + len(req.system_prompt.split()))
        completion_tokens = max(5, len(raw_text.split()))
        total_tokens = prompt_tokens + completion_tokens

        return LLMResult(
            model_used=req.model,
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=self.default_latency_ms,
            billed_cost_micro_usd=0,
        )
