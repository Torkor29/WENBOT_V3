"""Tests for input validation utilities."""

import pytest

from bot.services.validation import (
    validate_eth_address,
    validate_solana_address,
    validate_amount,
    sanitize_text,
    validate_private_key,
    validate_fee_rate,
)


class TestEthAddress:
    def test_valid_address(self):
        ok, _ = validate_eth_address("0x1234567890abcdef1234567890abcdef12345678")
        assert ok

    def test_valid_checksum_address(self):
        ok, _ = validate_eth_address("0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B")
        assert ok

    def test_too_short(self):
        ok, msg = validate_eth_address("0x1234")
        assert not ok
        assert "invalide" in msg.lower()

    def test_missing_prefix(self):
        ok, msg = validate_eth_address("1234567890abcdef1234567890abcdef12345678")
        assert not ok

    def test_empty(self):
        ok, msg = validate_eth_address("")
        assert not ok
        assert "vide" in msg.lower()

    def test_non_hex_chars(self):
        ok, _ = validate_eth_address("0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG")
        assert not ok


class TestSolanaAddress:
    def test_valid_address(self):
        ok, _ = validate_solana_address("DRpbCBMxVnDK7maPMoGQfFkVQkaZ7eUyEi8RYoq5eMTs")
        assert ok

    def test_too_short(self):
        ok, _ = validate_solana_address("abc")
        assert not ok

    def test_empty(self):
        ok, _ = validate_solana_address("")
        assert not ok

    def test_invalid_chars(self):
        ok, _ = validate_solana_address("0OIl" + "a" * 40)  # 0, O, I, l are invalid in base58
        assert not ok


class TestValidateAmount:
    def test_valid_amount(self):
        ok, val, _ = validate_amount("100.5")
        assert ok
        assert val == 100.5

    def test_integer(self):
        ok, val, _ = validate_amount("50")
        assert ok
        assert val == 50.0

    def test_zero_rejected(self):
        ok, _, msg = validate_amount("0")
        assert not ok

    def test_negative_rejected(self):
        ok, _, msg = validate_amount("-10")
        assert not ok

    def test_too_large(self):
        ok, _, msg = validate_amount("999999999")
        assert not ok
        assert "dépasser" in msg.lower()

    def test_custom_bounds(self):
        ok, val, _ = validate_amount("5", min_val=1, max_val=10)
        assert ok
        assert val == 5.0

        ok, _, _ = validate_amount("15", min_val=1, max_val=10)
        assert not ok

    def test_non_numeric(self):
        ok, _, msg = validate_amount("abc")
        assert not ok
        assert "invalide" in msg.lower()

    def test_spaces_trimmed(self):
        ok, val, _ = validate_amount("  42.5  ")
        assert ok
        assert val == 42.5


class TestSanitizeText:
    def test_normal_text(self):
        assert sanitize_text("Hello world") == "Hello world"

    def test_strips_whitespace(self):
        assert sanitize_text("  hello  ") == "hello"

    def test_html_escaped(self):
        result = sanitize_text("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_truncation(self):
        long_text = "a" * 1000
        result = sanitize_text(long_text, max_length=100)
        assert len(result) == 100

    def test_empty_string(self):
        assert sanitize_text("") == ""

    def test_none_returns_empty(self):
        assert sanitize_text(None) == ""


class TestValidatePrivateKey:
    def test_valid_key(self):
        ok, _ = validate_private_key("0x" + "a" * 64)
        assert ok

    def test_too_short(self):
        ok, msg = validate_private_key("short")
        assert not ok
        assert "courte" in msg.lower()

    def test_too_long(self):
        ok, msg = validate_private_key("a" * 300)
        assert not ok
        assert "longue" in msg.lower()

    def test_empty(self):
        ok, msg = validate_private_key("")
        assert not ok


class TestValidateFeeRate:
    def test_valid_rate(self):
        ok, _ = validate_fee_rate(0.01)
        assert ok

    def test_zero_valid(self):
        ok, _ = validate_fee_rate(0.0)
        assert ok

    def test_negative_invalid(self):
        ok, _ = validate_fee_rate(-0.01)
        assert not ok

    def test_too_high(self):
        ok, _ = validate_fee_rate(0.15)
        assert not ok

    def test_boundary(self):
        ok, _ = validate_fee_rate(0.1)
        assert ok
