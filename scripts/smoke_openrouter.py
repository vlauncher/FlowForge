"""Live smoke test for OpenRouter :free models integration.

Skips cleanly if OPENROUTER_API_KEY is unset in .env or environment.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.interface import LLMRequest
from app.ai.openrouter_client import OpenRouterClient
from app.ai.prompts.loader import get_prompt_template
from app.ai.validator import parse_and_validate_json
from app.core.config import get_settings


async def main() -> int:
    settings = get_settings()
    api_key = settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")

    if not api_key:
        print("[SMOKE] OPENROUTER_API_KEY is not set. Skipping live OpenRouter smoke test cleanly.")
        return 0

    print(
        f"[SMOKE] Testing OpenRouter live connection with base URL: {settings.openrouter_base_url}"
    )
    client = OpenRouterClient(
        api_key=api_key,
        base_url=settings.openrouter_base_url,
        timeout_seconds=30.0,
    )

    # Call 1: Ticket classification
    classify_tmpl = get_prompt_template("ticket_classify")
    ticket_text = "I received a duplicate charge of $49.00 on my mastercard statement this month."
    labels = ["billing", "bug", "feature_request", "other"]

    req1 = LLMRequest(
        model=settings.llm_model,
        fallback_models=settings.llm_fallback_models,
        system_prompt=classify_tmpl.format_system(),
        user_prompt=classify_tmpl.format_user(ticket_text, labels=labels),
        json_schema={
            "type": "object",
            "required": ["label", "confidence"],
            "properties": {
                "label": {"type": "string", "enum": labels},
                "confidence": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
            },
            "additionalProperties": False,
        },
        max_tokens=100,
    )

    print("\n--- Call 1: Ticket Classification ---")
    res1 = await client.generate_json(req1)
    print(f"Model used: {res1.model_used}")
    print(f"Latency: {res1.latency_ms} ms")
    print(
        f"Tokens: prompt={res1.prompt_tokens}, completion={res1.completion_tokens}, total={res1.total_tokens}"
    )
    validated1 = parse_and_validate_json(res1.raw_text, req1.json_schema)
    print(f"Validated JSON Output: {validated1}")

    # Call 2: Lead / contact extraction
    transform_tmpl = get_prompt_template("ticket_transform")
    lead_text = "Hello, my name is Marcus Vance from Vance Robotics. Please email me at mvance@vancerobotics.com regarding your enterprise tier."
    lead_schema = {
        "type": "object",
        "required": ["contact_name", "company", "contact_email"],
        "properties": {
            "contact_name": {"type": "string"},
            "company": {"type": "string"},
            "contact_email": {"type": "string"},
        },
        "additionalProperties": False,
    }

    req2 = LLMRequest(
        model=settings.llm_model,
        fallback_models=settings.llm_fallback_models,
        system_prompt=transform_tmpl.format_system(),
        user_prompt=transform_tmpl.format_user(lead_text),
        json_schema=lead_schema,
        max_tokens=250,
    )

    print("\n--- Call 2: Lead Extraction ---")
    res2 = await client.generate_json(req2)
    print(f"Model used: {res2.model_used}")
    print(f"Latency: {res2.latency_ms} ms")
    print(
        f"Tokens: prompt={res2.prompt_tokens}, completion={res2.completion_tokens}, total={res2.total_tokens}"
    )
    validated2 = parse_and_validate_json(res2.raw_text, lead_schema)
    print(f"Validated JSON Output: {validated2}")

    print("\n[SMOKE] All 2 OpenRouter live calls succeeded with valid structured JSON outputs.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
