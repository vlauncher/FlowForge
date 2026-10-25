"""Secret and PII redaction utilities."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY = re.compile(r"(?i)(password|secret|token|authorization|api[_-]?key|cookie)")


def redact(value: Any, *, max_depth: int = 8) -> Any:
    """Return a deep copy of value with sensitive dictionary keys replaced by '***'.

    Prevents infinite recursion on cyclical or deeply nested structures by bounding at max_depth.
    Never mutates the input argument.
    """
    if max_depth <= 0:
        return "…"

    if isinstance(value, dict):
        new_dict: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and SENSITIVE_KEY.search(k):
                new_dict[k] = "***"
            else:
                new_dict[k] = redact(v, max_depth=max_depth - 1)
        return new_dict

    if isinstance(value, list):
        return [redact(item, max_depth=max_depth - 1) for item in value]

    if isinstance(value, tuple):
        return tuple(redact(item, max_depth=max_depth - 1) for item in value)

    if isinstance(value, set):
        return {redact(item, max_depth=max_depth - 1) for item in value}

    return value
