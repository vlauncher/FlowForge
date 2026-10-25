"""Shared fixtures for E2E tests."""

from __future__ import annotations

from tests.integration.conftest import (  # noqa: F401
    app,
    client,
    db_engine,
    db_session,
    integration_settings,
    truncate_tables,
)
