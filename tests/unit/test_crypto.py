"""Unit tests for AES-256-GCM encryption and key rotation (P5-T01)."""

import base64
import os

import pytest

from app.core.crypto import decrypt_secret, encrypt_secret, parse_master_keys


def make_b64_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def test_encrypt_decrypt_round_trip() -> None:
    k1 = make_b64_key()
    keys_cfg = f"key-1:{k1}"

    secret = "sk_live_123456789abcdef!@#$"
    ciphertext, key_id = encrypt_secret(secret, master_keys_str=keys_cfg)

    assert key_id == "key-1"
    assert isinstance(ciphertext, bytes)
    assert len(ciphertext) > len(secret)

    decrypted = decrypt_secret(ciphertext, key_id="key-1", master_keys_str=keys_cfg)
    assert decrypted == secret


def test_tampered_ciphertext_fails() -> None:
    k1 = make_b64_key()
    keys_cfg = f"key-1:{k1}"

    secret = "super-secret-password"
    ciphertext, key_id = encrypt_secret(secret, master_keys_str=keys_cfg)

    # Flip one byte in the ciphertext
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0x01

    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_secret(bytes(tampered), key_id=key_id, master_keys_str=keys_cfg)


def test_wrong_key_fails() -> None:
    k1 = make_b64_key()
    k2 = make_b64_key()

    ciphertext, _ = encrypt_secret("my-token", master_keys_str=f"key-1:{k1}")

    # Attempt to decrypt using key-2
    with pytest.raises(ValueError, match="Decryption failed"):
        decrypt_secret(ciphertext, key_id="key-2", master_keys_str=f"key-2:{k2}")


def test_key_rotation_support() -> None:
    old_key = make_b64_key()
    new_key = make_b64_key()

    # Old configuration: old_key is active
    old_cfg = f"v1:{old_key}"
    ciphertext_v1, key_id_v1 = encrypt_secret("rotating-secret", master_keys_str=old_cfg)
    assert key_id_v1 == "v1"

    # Rotated configuration: new_key is first (active), old_key preserved for decryption
    rotated_cfg = f"v2:{new_key},v1:{old_key}"

    # Decrypts existing ciphertext using v1
    decrypted_old = decrypt_secret(ciphertext_v1, key_id="v1", master_keys_str=rotated_cfg)
    assert decrypted_old == "rotating-secret"

    # New encryption automatically uses active key v2
    ciphertext_v2, key_id_v2 = encrypt_secret(decrypted_old, master_keys_str=rotated_cfg)
    assert key_id_v2 == "v2"

    decrypted_new = decrypt_secret(ciphertext_v2, key_id="v2", master_keys_str=rotated_cfg)
    assert decrypted_new == "rotating-secret"


def test_invalid_key_length_validation() -> None:
    bad_key = base64.b64encode(b"short-16-bytes!").decode("ascii")
    with pytest.raises(ValueError, match="must be exactly 32 bytes"):
        parse_master_keys(f"k1:{bad_key}")
