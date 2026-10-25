"""Unit tests for OpenAPI export and consistency."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent.parent
OPENAPI_FILE = ROOT / "openapi.json"


def test_openapi_contains_health_and_matches_file() -> None:
    """P1-T15: app.openapi() contains /health and /ready; matches committed openapi.json."""
    app = create_app(Settings(app_env="dev"))
    current_schema = app.openapi()

    assert "/health" in current_schema["paths"]
    assert "/ready" in current_schema["paths"]

    assert OPENAPI_FILE.exists(), "openapi.json must exist in the root directory"
    committed_schema = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))

    assert current_schema == committed_schema
