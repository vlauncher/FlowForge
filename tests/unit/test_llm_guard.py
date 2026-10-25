"""Unit tests for free-tier model guards in Settings and assert_free_model (P6-T01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.interface import LLMNonFreeModelError, assert_free_model
from app.core.config import Settings


def test_assert_free_model_accepts_valid_free_models() -> None:
    """assert_free_model must allow openrouter/free and any string ending in :free."""
    assert_free_model("openrouter/free")
    assert_free_model("meta-llama/llama-3.3-70b-instruct:free")
    assert_free_model("google/gemini-2.0-flash-exp:free")
    assert_free_model("deepseek/deepseek-r1:free")


def test_assert_free_model_rejects_paid_models() -> None:
    """assert_free_model must raise LLMNonFreeModelError on paid models."""
    with pytest.raises(LLMNonFreeModelError) as exc_info:
        assert_free_model("openai/gpt-4o")
    assert exc_info.value.code == "LLM_NON_FREE_MODEL"

    with pytest.raises(LLMNonFreeModelError):
        assert_free_model("anthropic/claude-3.5-sonnet")

    with pytest.raises(LLMNonFreeModelError):
        assert_free_model("meta-llama/llama-3.3-70b-instruct")


def test_settings_validation_rejects_non_free_models() -> None:
    """Settings must reject non-free models in llm_model and llm_fallback_models."""
    # Valid
    s1 = Settings(
        llm_model="openrouter/free",
        llm_fallback_models=["meta-llama/llama-3.3-70b-instruct:free"],
    )
    assert s1.llm_model == "openrouter/free"
    assert s1.llm_fallback_models == ["meta-llama/llama-3.3-70b-instruct:free"]

    # Invalid primary model
    with pytest.raises(ValidationError, match="LLM_NON_FREE_MODEL"):
        Settings(llm_model="openai/gpt-4o")

    # Invalid fallback model
    with pytest.raises(ValidationError, match="LLM_NON_FREE_MODEL"):
        Settings(
            llm_model="openrouter/free",
            llm_fallback_models=["openai/gpt-4o-mini"],
        )
