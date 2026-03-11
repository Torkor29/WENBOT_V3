"""AES-256-GCM encryption for private keys.

Keys are encrypted at rest and only decrypted in memory when signing transactions.
The encryption key is derived from the master ENCRYPTION_KEY + a per-user salt.
"""

import hashlib
import os
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# Salt size in bytes
SALT_SIZE = 16
# Nonce size for AES-GCM (96 bits recommended by NIST)
NONCE_SIZE = 12
# Key size: 256 bits
KEY_SIZE = 32


@dataclass
class EncryptedPayload:
    """Packed format: salt (16) + nonce (12) + ciphertext (variable)."""
    salt: bytes
    nonce: bytes
    ciphertext: bytes

    def pack(self) -> bytes:
        return self.salt + self.nonce + self.ciphertext

    @classmethod
    def unpack(cls, data: bytes) -> "EncryptedPayload":
        if len(data) < SALT_SIZE + NONCE_SIZE + 1:
            raise ValueError("Encrypted payload too short")
        salt = data[:SALT_SIZE]
        nonce = data[SALT_SIZE : SALT_SIZE + NONCE_SIZE]
        ciphertext = data[SALT_SIZE + NONCE_SIZE :]
        return cls(salt=salt, nonce=nonce, ciphertext=ciphertext)


def _derive_key(master_key: str, user_id: str, salt: bytes) -> bytes:
    """Derive a per-user encryption key using HKDF-like construction via PBKDF2."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        master_key.encode("utf-8"),
        salt + user_id.encode("utf-8"),
        iterations=100_000,
        dklen=KEY_SIZE,
    )
    return dk


def encrypt_private_key(
    private_key: str, master_key: str, user_id: str
) -> bytes:
    """Encrypt a private key string using AES-256-GCM.

    Returns packed bytes: salt + nonce + ciphertext.
    The private_key is immediately cleared from scope after encryption.
    """
    if not private_key:
        raise ValueError("Private key cannot be empty")
    if not master_key:
        raise ValueError("Master encryption key not configured")

    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    derived_key = _derive_key(master_key, user_id, salt)

    aesgcm = AESGCM(derived_key)
    ciphertext = aesgcm.encrypt(
        nonce,
        private_key.encode("utf-8"),
        # Additional authenticated data: user_id to bind ciphertext to user
        user_id.encode("utf-8"),
    )

    payload = EncryptedPayload(salt=salt, nonce=nonce, ciphertext=ciphertext)
    return payload.pack()


def decrypt_private_key(
    encrypted_data: bytes, master_key: str, user_id: str
) -> str:
    """Decrypt a private key. Used only in-memory at signing time.

    WARNING: The returned string must not be logged or persisted.
    """
    if not encrypted_data:
        raise ValueError("No encrypted data provided")
    if not master_key:
        raise ValueError("Master encryption key not configured")

    payload = EncryptedPayload.unpack(encrypted_data)
    derived_key = _derive_key(master_key, user_id, payload.salt)

    aesgcm = AESGCM(derived_key)
    plaintext = aesgcm.decrypt(
        payload.nonce,
        payload.ciphertext,
        user_id.encode("utf-8"),
    )

    return plaintext.decode("utf-8")
