"""AES-256-GCM encryption / decryption for wallet private keys."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import shared.config as _cfg

_NONCE_LENGTH = 12  # 96-bit nonce recommended for AES-GCM


def _get_key() -> bytes:
    """Derive the 32-byte AES key from the hex-encoded master key."""
    master_key = _cfg.ENCRYPTION_MASTER_KEY
    if not master_key or len(master_key) != 64:
        raise ValueError(
            "ENCRYPTION_MASTER_KEY must be a 64-character hex string (32 bytes)"
        )
    return bytes.fromhex(master_key)


def encrypt(private_key: str) -> str:
    """Encrypt a private key string with AES-256-GCM.

    Returns:
        Base64-encoded blob containing ``nonce || ciphertext`` (nonce is 12 bytes).
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LENGTH)
    ciphertext = aesgcm.encrypt(nonce, private_key.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt(encrypted_blob: str) -> str:
    """Decrypt a base64-encoded blob produced by :func:`encrypt`.

    Returns:
        The original private key string.
    """
    key = _get_key()
    raw = base64.b64decode(encrypted_blob)
    nonce = raw[:_NONCE_LENGTH]
    ciphertext = raw[_NONCE_LENGTH:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
