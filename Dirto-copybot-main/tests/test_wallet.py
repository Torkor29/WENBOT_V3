"""Tests for wallet creation, encryption, and decryption."""

from __future__ import annotations

import os
import re

import pytest

# Set a deterministic master key for tests before importing wallet modules
os.environ["ENCRYPTION_MASTER_KEY"] = "a" * 64


from wallet.create import create_wallet  # noqa: E402
from wallet.encrypt import decrypt, encrypt  # noqa: E402


class TestCreateWallet:
    """Wallet creation tests."""

    def test_address_format(self) -> None:
        address, _ = create_wallet()
        assert address.startswith("0x")
        assert len(address) == 42
        assert re.fullmatch(r"0x[0-9a-fA-F]{40}", address)

    def test_private_key_not_empty(self) -> None:
        _, private_key = create_wallet()
        assert private_key
        assert len(private_key) > 0

    def test_private_key_is_hex(self) -> None:
        _, private_key = create_wallet()
        assert private_key.startswith("0x")
        assert re.fullmatch(r"0x[0-9a-fA-F]+", private_key)

    def test_unique_wallets(self) -> None:
        addr1, key1 = create_wallet()
        addr2, key2 = create_wallet()
        assert addr1 != addr2
        assert key1 != key2


class TestEncryptDecrypt:
    """Encryption round-trip tests."""

    def test_round_trip(self) -> None:
        original = "0xdeadbeef1234567890abcdef1234567890abcdef1234567890abcdef12345678"
        encrypted = encrypt(original)
        decrypted = decrypt(encrypted)
        assert decrypted == original

    def test_round_trip_with_wallet(self) -> None:
        _, private_key = create_wallet()
        encrypted = encrypt(private_key)
        decrypted = decrypt(encrypted)
        assert decrypted == private_key

    def test_unique_nonce(self) -> None:
        """Each call to encrypt must produce a different ciphertext (unique nonce)."""
        plaintext = "0x" + "ab" * 32
        blob1 = encrypt(plaintext)
        blob2 = encrypt(plaintext)
        assert blob1 != blob2

    def test_encrypted_is_base64(self) -> None:
        encrypted = encrypt("0x1234")
        import base64

        # Should not raise
        raw = base64.b64decode(encrypted)
        assert len(raw) > 12  # at least nonce (12) + some ciphertext

    def test_wrong_key_fails(self) -> None:
        original = "0xsecretkey"
        encrypted = encrypt(original)

        # Tamper with the module-level key temporarily
        import wallet.encrypt as enc_mod
        import shared.config as cfg_mod

        saved = cfg_mod.ENCRYPTION_MASTER_KEY
        try:
            cfg_mod.ENCRYPTION_MASTER_KEY = "b" * 64
            with pytest.raises(Exception):
                decrypt(encrypted)
        finally:
            cfg_mod.ENCRYPTION_MASTER_KEY = saved
