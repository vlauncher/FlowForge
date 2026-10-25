#!/usr/bin/env python3
"""Batch CLI script to re-encrypt credentials under the current active master key."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret, get_active_key, parse_master_keys
from app.infrastructure.db.session import get_session_factory
from app.modules.integrations.models import IntegrationCredential

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rotate_secrets")


async def rotate_all_secrets() -> int:
    """Find all credentials encrypted with an inactive master key and re-encrypt them."""
    settings = get_settings()
    master_keys = parse_master_keys(settings.secrets_master_keys)
    active_key_id, _ = get_active_key(master_keys)
    logger.info("Current active master key: '%s'", active_key_id)

    factory = get_session_factory()
    rotated_count = 0

    async with factory() as session:
        async with session.begin():
            stmt = select(IntegrationCredential).where(
                IntegrationCredential.key_id != active_key_id
            )
            result = await session.execute(stmt)
            creds_to_rotate = list(result.scalars().all())

            logger.info(
                "Found %d credentials encrypted under older master keys", len(creds_to_rotate)
            )

            for cred in creds_to_rotate:
                logger.info(
                    "Re-encrypting credential '%s' (org=%s) from key '%s' -> '%s'",
                    cred.name,
                    cred.org_id,
                    cred.key_id,
                    active_key_id,
                )
                plaintext = decrypt_secret(cred.encrypted_secret, cred.key_id)
                new_ciphertext, new_key_id = encrypt_secret(plaintext)
                cred.encrypted_secret = new_ciphertext
                cred.key_id = new_key_id
                cred.rotated_at = datetime.now(UTC)
                rotated_count += 1

    logger.info(
        "Successfully rotated %d credentials to active key '%s'", rotated_count, active_key_id
    )
    return rotated_count


def main() -> None:
    asyncio.run(rotate_all_secrets())
    sys.exit(0)


if __name__ == "__main__":
    main()
