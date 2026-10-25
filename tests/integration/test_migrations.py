"""Integration test for Alembic migrations forward and backward (P2-T01)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.core.config import Settings

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.asyncio
async def test_migration_upgrade_downgrade_round_trip(integration_settings: Settings) -> None:
    """P2-T01: alembic upgrade head -> downgrade base -> upgrade head all succeed."""
    alembic_ini_path = ROOT / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))

    def run_migrations() -> None:
        command.upgrade(alembic_cfg, "head")
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")

    await asyncio.to_thread(run_migrations)
