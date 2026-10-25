"""Readiness probe registry and check runner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

ReadinessCheck = Callable[[], Awaitable[None]]

_REGISTRY: dict[str, ReadinessCheck] = {}


def register_check(name: str, fn: ReadinessCheck) -> None:
    """Register a readiness probe check function."""
    _REGISTRY[name] = fn


def clear_checks() -> None:
    """Clear all registered checks (primarily for test isolation)."""
    _REGISTRY.clear()


async def run_checks() -> dict[str, str]:
    """Execute all registered checks concurrently with a 2-second timeout per check.

    Returns a dict mapping check name to 'ok' or 'fail'.
    """
    results: dict[str, str] = {}
    if not _REGISTRY:
        return results

    async def _execute(name: str, check_fn: ReadinessCheck) -> tuple[str, str]:
        try:
            await asyncio.wait_for(check_fn(), timeout=2.0)
            return name, "ok"
        except Exception:
            return name, "fail"

    tasks = [_execute(name, fn) for name, fn in _REGISTRY.items()]
    completed = await asyncio.gather(*tasks)
    for name, status in completed:
        results[name] = status

    return results
