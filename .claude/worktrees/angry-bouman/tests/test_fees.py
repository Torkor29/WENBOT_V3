"""Tests for platform fee service — 100% coverage required."""

import os
import pytest
import pytest_asyncio

os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"

from bot.services.fees import (
    calculate_fee,
    format_fee_display,
    transfer_fee_on_chain,
    FeeCalculationError,
    FeeTransferError,
    FeeResult,
)


class TestCalculateFee:
    def test_standard_1_percent(self):
        result = calculate_fee(100.0)
        assert result.fee_amount == 1.0
        assert result.net_amount == 99.0
        assert result.fee_rate == 0.01
        assert result.gross_amount == 100.0

    def test_small_amount(self):
        result = calculate_fee(1.0)
        assert result.fee_amount == 0.01
        assert result.net_amount == 0.99

    def test_large_amount(self):
        result = calculate_fee(10000.0)
        assert result.fee_amount == 100.0
        assert result.net_amount == 9900.0

    def test_fractional_amount(self):
        result = calculate_fee(45.0)
        assert result.fee_amount == 0.45
        assert result.net_amount == 44.55

    def test_custom_fee_rate(self):
        result = calculate_fee(100.0, fee_rate=0.02)
        assert result.fee_amount == 2.0
        assert result.net_amount == 98.0
        assert result.fee_rate == 0.02

    def test_zero_fee_rate(self):
        result = calculate_fee(100.0, fee_rate=0.0)
        assert result.fee_amount == 0.0
        assert result.net_amount == 100.0

    def test_fee_plus_net_equals_gross(self):
        for amount in [1.0, 10.0, 50.5, 100.0, 999.99, 10000.0]:
            result = calculate_fee(amount)
            assert round(result.fee_amount + result.net_amount, 6) == amount

    def test_fees_wallet_set(self):
        result = calculate_fee(100.0)
        assert result.fees_wallet == "0xTestFeesWallet"

    def test_negative_amount_raises(self):
        with pytest.raises(FeeCalculationError, match="positive"):
            calculate_fee(-10.0)

    def test_zero_amount_raises(self):
        with pytest.raises(FeeCalculationError, match="positive"):
            calculate_fee(0.0)

    def test_invalid_fee_rate_raises(self):
        with pytest.raises(FeeCalculationError, match="between 0 and 1"):
            calculate_fee(100.0, fee_rate=1.5)

    def test_negative_fee_rate_raises(self):
        with pytest.raises(FeeCalculationError, match="between 0 and 1"):
            calculate_fee(100.0, fee_rate=-0.01)

    def test_precision_rounding(self):
        # 33.33 * 0.01 = 0.3333 → should round to 0.3333
        result = calculate_fee(33.33)
        assert result.fee_amount == 0.3333
        assert result.net_amount == 32.9967

    def test_very_small_amount(self):
        result = calculate_fee(0.01)
        assert result.fee_amount == 0.0001
        assert result.net_amount == 0.0099

    def test_missing_fees_wallet_raises(self):
        """Fee calculation fails if FEES_WALLET not configured."""
        from bot.config import settings
        original = settings.fees_wallet
        settings.fees_wallet = ""
        try:
            with pytest.raises(FeeCalculationError, match="FEES_WALLET"):
                calculate_fee(100.0)
        finally:
            settings.fees_wallet = original


class TestTransferFeeOnChain:
    @pytest.mark.asyncio
    async def test_transfer_calls_web3_client(self):
        """Fee transfer now delegates to polygon_client.transfer_usdc."""
        fee_result = FeeResult(
            gross_amount=100.0,
            fee_rate=0.01,
            fee_amount=1.0,
            net_amount=99.0,
            fees_wallet="0xtest",
        )
        from unittest.mock import AsyncMock, patch
        from bot.services.web3_client import TransferResult

        mock_result = TransferResult(success=True, tx_hash="0xfee123")
        with patch(
            "bot.services.web3_client.polygon_client.transfer_usdc",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            tx = await transfer_fee_on_chain(fee_result, "0xuser", "private_key")
            assert tx == "0xfee123"

    @pytest.mark.asyncio
    async def test_transfer_failure_raises(self):
        """Fee transfer raises FeeTransferError on failure."""
        fee_result = FeeResult(
            gross_amount=100.0,
            fee_rate=0.01,
            fee_amount=1.0,
            net_amount=99.0,
            fees_wallet="0xtest",
        )
        from unittest.mock import AsyncMock, patch
        from bot.services.web3_client import TransferResult

        mock_result = TransferResult(success=False, error="insufficient gas")
        with patch(
            "bot.services.web3_client.polygon_client.transfer_usdc",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            with pytest.raises(FeeTransferError, match="insufficient gas"):
                await transfer_fee_on_chain(fee_result, "0xuser", "pk")

    @pytest.mark.asyncio
    async def test_zero_fee_returns_no_fee(self):
        fee_result = FeeResult(
            gross_amount=100.0,
            fee_rate=0.0,
            fee_amount=0.0,
            net_amount=100.0,
            fees_wallet="0xtest",
        )
        tx = await transfer_fee_on_chain(fee_result, "0xuser", "pk")
        assert tx == "no_fee"


class TestFormatFeeDisplay:
    def test_format_standard(self):
        fee_result = FeeResult(
            gross_amount=45.0,
            fee_rate=0.01,
            fee_amount=0.45,
            net_amount=44.55,
            fees_wallet="0xtest",
        )
        display = format_fee_display(fee_result)
        assert "45.00 USDC" in display
        assert "-0.45 USDC" in display
        assert "44.55 USDC" in display
        assert "1%" in display

    def test_format_contains_emoji(self):
        fee_result = FeeResult(
            gross_amount=100.0,
            fee_rate=0.01,
            fee_amount=1.0,
            net_amount=99.0,
            fees_wallet="0xtest",
        )
        display = format_fee_display(fee_result)
        assert "💵" in display
        assert "💸" in display
        assert "✅" in display
