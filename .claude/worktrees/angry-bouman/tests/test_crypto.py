"""Tests for AES-256-GCM encryption service."""

import pytest
from bot.services.crypto import (
    encrypt_private_key,
    decrypt_private_key,
    EncryptedPayload,
    SALT_SIZE,
    NONCE_SIZE,
)

MASTER_KEY = "test_master_key_for_encryption_32"
USER_ID = "user-abc-123"
PRIVATE_KEY = "0xdeadbeef1234567890abcdef"


class TestEncryptDecrypt:
    def test_encrypt_returns_bytes(self):
        result = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        assert isinstance(result, bytes)
        assert len(result) > SALT_SIZE + NONCE_SIZE

    def test_decrypt_returns_original(self):
        encrypted = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        decrypted = decrypt_private_key(encrypted, MASTER_KEY, USER_ID)
        assert decrypted == PRIVATE_KEY

    def test_different_encryptions_produce_different_ciphertexts(self):
        enc1 = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        enc2 = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        # Different salt/nonce each time
        assert enc1 != enc2

    def test_both_decrypt_to_same_value(self):
        enc1 = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        enc2 = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        assert decrypt_private_key(enc1, MASTER_KEY, USER_ID) == PRIVATE_KEY
        assert decrypt_private_key(enc2, MASTER_KEY, USER_ID) == PRIVATE_KEY

    def test_wrong_master_key_fails(self):
        encrypted = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        with pytest.raises(Exception):
            decrypt_private_key(encrypted, "wrong_key_completely_invalid!", USER_ID)

    def test_wrong_user_id_fails(self):
        encrypted = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        with pytest.raises(Exception):
            decrypt_private_key(encrypted, MASTER_KEY, "different-user")

    def test_tampered_ciphertext_fails(self):
        encrypted = encrypt_private_key(PRIVATE_KEY, MASTER_KEY, USER_ID)
        tampered = bytearray(encrypted)
        tampered[-1] ^= 0xFF  # Flip last byte
        with pytest.raises(Exception):
            decrypt_private_key(bytes(tampered), MASTER_KEY, USER_ID)

    def test_empty_private_key_raises(self):
        with pytest.raises(ValueError, match="Private key cannot be empty"):
            encrypt_private_key("", MASTER_KEY, USER_ID)

    def test_empty_master_key_raises(self):
        with pytest.raises(ValueError, match="Master encryption key not configured"):
            encrypt_private_key(PRIVATE_KEY, "", USER_ID)

    def test_empty_encrypted_data_raises(self):
        with pytest.raises(ValueError, match="No encrypted data provided"):
            decrypt_private_key(b"", MASTER_KEY, USER_ID)

    def test_short_payload_raises(self):
        with pytest.raises(ValueError, match="too short"):
            decrypt_private_key(b"tooshort", MASTER_KEY, USER_ID)


class TestEncryptedPayload:
    def test_pack_unpack_roundtrip(self):
        payload = EncryptedPayload(
            salt=b"a" * SALT_SIZE,
            nonce=b"b" * NONCE_SIZE,
            ciphertext=b"encrypted_data_here",
        )
        packed = payload.pack()
        unpacked = EncryptedPayload.unpack(packed)

        assert unpacked.salt == payload.salt
        assert unpacked.nonce == payload.nonce
        assert unpacked.ciphertext == payload.ciphertext

    def test_pack_size(self):
        payload = EncryptedPayload(
            salt=b"a" * SALT_SIZE,
            nonce=b"b" * NONCE_SIZE,
            ciphertext=b"data",
        )
        packed = payload.pack()
        assert len(packed) == SALT_SIZE + NONCE_SIZE + 4
