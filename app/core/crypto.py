"""AES-256-GCM authenticated encryption and decryption for tenant credentials."""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def parse_master_keys(keys_str: str) -> dict[str, bytes]:
    """Parse comma-separated 'key_id:base64_key' pairs into raw 32-byte AES keys."""
    keys: dict[str, bytes] = {}
    if not keys_str or not keys_str.strip():
        return keys

    for item in keys_str.split(","):
        trimmed = item.strip()
        if not trimmed:
            continue
        parts = trimmed.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid master key format: '{trimmed}' (expected 'key_id:base64')")
        key_id, b64_key = parts[0].strip(), parts[1].strip()
        try:
            raw_key = base64.b64decode(b64_key)
        except Exception as exc:
            raise ValueError(f"Failed to base64-decode master key '{key_id}': {exc}") from exc

        if len(raw_key) != 32:
            raise ValueError(
                f"Master key '{key_id}' must be exactly 32 bytes (AES-256), got {len(raw_key)}"
            )
        keys[key_id] = raw_key

    return keys


def get_active_key(master_keys: Mapping[str, bytes]) -> tuple[str, bytes]:
    """Return the active (first) master key pair for new encryptions."""
    if not master_keys:
        raise ValueError("No master encryption keys configured")
    key_id = next(iter(master_keys))
    return key_id, master_keys[key_id]


def encrypt_secret(
    plaintext: str | bytes,
    master_keys_str: str | None = None,
) -> tuple[bytes, str]:
    """Encrypt plaintext using AES-256-GCM with the active master key.

    Returns (nonce_prepended_ciphertext, key_id).
    """
    settings = get_settings()
    raw_keys_str = master_keys_str if master_keys_str is not None else settings.secrets_master_keys
    master_keys = parse_master_keys(raw_keys_str)
    active_key_id, raw_key = get_active_key(master_keys)

    data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext

    # Generate 12-byte cryptographic random nonce (RFC 5116)
    nonce = os.urandom(12)
    aesgcm = AESGCM(raw_key)
    ciphertext = aesgcm.encrypt(nonce, data, None)

    # Prepend 12-byte nonce directly to ciphertext
    return nonce + ciphertext, active_key_id


def decrypt_secret(
    encrypted_secret: bytes,
    key_id: str,
    master_keys_str: str | None = None,
) -> str:
    """Decrypt ciphertext using the master key matching key_id."""
    settings = get_settings()
    raw_keys_str = master_keys_str if master_keys_str is not None else settings.secrets_master_keys
    master_keys = parse_master_keys(raw_keys_str)

    if key_id not in master_keys:
        raise ValueError(f"Encryption master key '{key_id}' not found in configuration")

    if len(encrypted_secret) < 28:  # 12-byte nonce + 16-byte tag min
        raise ValueError("Invalid ciphertext length: must be at least 28 bytes")

    nonce = encrypted_secret[:12]
    ciphertext = encrypted_secret[12:]

    aesgcm = AESGCM(master_keys[key_id])
    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")
    except (InvalidTag, Exception) as exc:
        raise ValueError(
            "Decryption failed: corrupted ciphertext, invalid tag, or wrong key"
        ) from exc
