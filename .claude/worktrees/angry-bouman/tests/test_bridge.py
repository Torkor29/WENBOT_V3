"""Tests for bridge service — quote comparison and execution."""

import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"
os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"

from bot.services.bridge import (
    BridgeQuote,
    BridgeProvider,
    BridgeResult,
    BridgeStatus,
    get_best_quote,
    execute_bridge,
    check_bridge_status,
)


class TestBridgeQuote:
    def test_quote_creation(self):
        quote = BridgeQuote(
            provider=BridgeProvider.LIFI,
            input_amount=1.0,
            output_amount=150.0,
            fee_usd=0.5,
            estimated_time_seconds=300,
        )
        assert quote.provider == BridgeProvider.LIFI
        assert quote.output_amount == 150.0

    def test_quote_with_route_data(self):
        quote = BridgeQuote(
            provider=BridgeProvider.ACROSS,
            input_amount=2.0,
            output_amount=290.0,
            fee_usd=1.0,
            estimated_time_seconds=180,
            route_data={"test": True},
        )
        assert quote.route_data == {"test": True}


class TestBridgeResult:
    def test_success_result(self):
        r = BridgeResult(
            success=True,
            provider=BridgeProvider.LIFI,
            input_amount=1.0,
            output_amount=150.0,
            tx_hash="0xabc",
            status=BridgeStatus.COMPLETED,
        )
        assert r.success
        assert r.status == BridgeStatus.COMPLETED

    def test_failure_result(self):
        r = BridgeResult(
            success=False,
            error="Network error",
            status=BridgeStatus.FAILED,
        )
        assert not r.success
        assert r.error == "Network error"


class TestGetBestQuote:
    @pytest.mark.asyncio
    async def test_no_quotes_returns_none(self):
        """If all providers fail, return None."""
        with patch(
            "bot.services.bridge.get_lifi_quote",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "bot.services.bridge.get_across_quote",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await get_best_quote(1.0, "wallet1", "wallet2")
            assert result is None

    @pytest.mark.asyncio
    async def test_single_quote_returned(self):
        """If only one provider responds, use that one."""
        lifi_quote = BridgeQuote(
            provider=BridgeProvider.LIFI,
            input_amount=1.0,
            output_amount=150.0,
            fee_usd=0.5,
            estimated_time_seconds=300,
        )

        with patch(
            "bot.services.bridge.get_lifi_quote",
            new_callable=AsyncMock,
            return_value=lifi_quote,
        ), patch(
            "bot.services.bridge.get_across_quote",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await get_best_quote(1.0, "w1", "w2")
            assert result is not None
            assert result.provider == BridgeProvider.LIFI

    @pytest.mark.asyncio
    async def test_best_quote_wins(self):
        """The quote with highest output amount should win."""
        lifi_quote = BridgeQuote(
            provider=BridgeProvider.LIFI,
            input_amount=1.0,
            output_amount=148.0,
            fee_usd=1.0,
            estimated_time_seconds=300,
        )
        across_quote = BridgeQuote(
            provider=BridgeProvider.ACROSS,
            input_amount=1.0,
            output_amount=151.0,
            fee_usd=0.3,
            estimated_time_seconds=180,
        )

        with patch(
            "bot.services.bridge.get_lifi_quote",
            new_callable=AsyncMock,
            return_value=lifi_quote,
        ), patch(
            "bot.services.bridge.get_across_quote",
            new_callable=AsyncMock,
            return_value=across_quote,
        ):
            result = await get_best_quote(1.0, "w1", "w2")
            assert result.provider == BridgeProvider.ACROSS
            assert result.output_amount == 151.0


class TestExecuteBridge:
    @pytest.mark.asyncio
    async def test_unsupported_provider(self):
        """Non-LiFi providers return not-implemented error."""
        quote = BridgeQuote(
            provider=BridgeProvider.ACROSS,
            input_amount=1.0,
            output_amount=150.0,
            fee_usd=0.5,
            estimated_time_seconds=180,
        )
        result = await execute_bridge(quote, "private_key")
        assert not result.success
        assert "not implemented" in result.error

    @pytest.mark.asyncio
    async def test_lifi_no_tx_data(self):
        """LiFi bridge fails if quote has no transaction data."""
        quote = BridgeQuote(
            provider=BridgeProvider.LIFI,
            input_amount=1.0,
            output_amount=150.0,
            fee_usd=0.5,
            estimated_time_seconds=300,
            route_data={},  # No transactionRequest
        )
        result = await execute_bridge(quote, "private_key")
        assert not result.success


class TestBridgeStatus:
    def test_status_enum(self):
        assert BridgeStatus.COMPLETED == "completed"
        assert BridgeStatus.FAILED == "failed"
        assert BridgeStatus.PENDING == "pending"
        assert BridgeStatus.BRIDGING == "bridging"
