"""Tests for Web3 client — USDC transfers and balance queries."""

import pytest

from bot.services.web3_client import usdc_to_wei, wei_to_usdc, TransferResult


class TestUsdcConversion:
    def test_usdc_to_wei(self):
        assert usdc_to_wei(1.0) == 1_000_000
        assert usdc_to_wei(100.0) == 100_000_000
        assert usdc_to_wei(0.5) == 500_000
        assert usdc_to_wei(0.000001) == 1

    def test_wei_to_usdc(self):
        assert wei_to_usdc(1_000_000) == 1.0
        assert wei_to_usdc(100_000_000) == 100.0
        assert wei_to_usdc(500_000) == 0.5
        assert wei_to_usdc(1) == 0.000001

    def test_roundtrip(self):
        for amount in [0.01, 1.0, 10.5, 100.0, 999.999999]:
            assert wei_to_usdc(usdc_to_wei(amount)) == pytest.approx(amount, abs=1e-6)


class TestTransferResult:
    def test_success_result(self):
        r = TransferResult(success=True, tx_hash="0xabc123", gas_used=65000)
        assert r.success
        assert r.tx_hash == "0xabc123"
        assert r.error is None

    def test_failure_result(self):
        r = TransferResult(success=False, error="insufficient funds")
        assert not r.success
        assert r.error == "insufficient funds"
        assert r.tx_hash is None
