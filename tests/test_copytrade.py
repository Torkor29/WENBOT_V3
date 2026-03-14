"""Tests for copytrade engine — the core trade execution flow."""

import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"
os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"

from bot.services.copytrade import CopyTradeEngine
from bot.services.monitor import TradeSignal
from bot.services.fees import FeeResult
from bot.services.sizing import SizingError
from bot.services.web3_client import TransferResult
from bot.services.polymarket import OrderResult
from bot.models.user import User, UserRole
from bot.models.settings import UserSettings, SizingMode
from bot.models.trade import Trade, TradeStatus, TradeSide


MASTER_WALLET = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def make_signal(**overrides):
    defaults = {
        "master_wallet": MASTER_WALLET,
        "market_id": "market-001",
        "token_id": "token-abc",
        "outcome": "YES",
        "side": "BUY",
        "size": 100.0,
        "price": 0.50,
        "master_pnl_pct": 5.0,
        "market_question": "Test market?",
    }
    defaults.update(overrides)
    return TradeSignal(**defaults)


class TestCopyTradeEngine:
    def test_engine_creation(self):
        engine = CopyTradeEngine()
        assert engine._bot is None

    def test_engine_with_bot(self):
        mock_bot = MagicMock()
        engine = CopyTradeEngine(telegram_bot=mock_bot)
        assert engine._bot is mock_bot

    @pytest.mark.asyncio
    async def test_handle_signal_no_followers(self):
        """Engine should skip if no followers for this master wallet."""
        engine = CopyTradeEngine()

        with patch(
            "bot.services.copytrade.get_followers_of_wallet",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await engine.handle_signal(make_signal())

    @pytest.mark.asyncio
    async def test_passes_filters_blacklisted(self):
        """Blacklisted markets should be filtered out."""
        engine = CopyTradeEngine()

        settings_mock = MagicMock()
        settings_mock.categories = []
        settings_mock.blacklisted_markets = ["market-blocked"]

        signal = make_signal(market_id="market-blocked")
        assert not await engine._passes_filters(settings_mock, signal)

    @pytest.mark.asyncio
    async def test_passes_filters_allowed(self):
        """Non-blacklisted markets should pass."""
        engine = CopyTradeEngine()

        settings_mock = MagicMock()
        settings_mock.categories = []
        settings_mock.blacklisted_markets = ["market-blocked"]

        signal = make_signal(market_id="market-ok")
        assert await engine._passes_filters(settings_mock, signal)

    def test_needs_confirmation_manual_on(self):
        """If manual confirmation is on, always needs confirmation."""
        engine = CopyTradeEngine()
        settings_mock = MagicMock()
        settings_mock.manual_confirmation = True
        settings_mock.confirmation_threshold_usdc = 50.0
        assert engine._needs_confirmation(settings_mock, 10.0)

    def test_needs_confirmation_threshold(self):
        """Amounts above threshold need confirmation."""
        engine = CopyTradeEngine()
        settings_mock = MagicMock()
        settings_mock.manual_confirmation = False
        settings_mock.confirmation_threshold_usdc = 50.0
        assert engine._needs_confirmation(settings_mock, 100.0)
        assert not engine._needs_confirmation(settings_mock, 30.0)


class TestFeeIntegration:
    """Test that fee calculation integrates correctly with the engine."""

    def test_fee_calculated_before_trade(self):
        """Fee must be calculated on gross amount before execution."""
        from bot.services.fees import calculate_fee

        fee = calculate_fee(100.0)
        assert fee.fee_amount == 1.0
        assert fee.net_amount == 99.0
        # Net amount is what goes into the trade
        assert fee.gross_amount == fee.net_amount + fee.fee_amount

    def test_fee_result_dataclass(self):
        result = FeeResult(
            gross_amount=50.0,
            fee_rate=0.01,
            fee_amount=0.5,
            net_amount=49.5,
            fees_wallet="0xFees",
        )
        assert result.gross_amount - result.fee_amount == result.net_amount


class TestTradeSignalProcessing:
    """Test signal processing logic without actual API calls."""

    def test_signal_buy(self):
        signal = make_signal(side="BUY")
        assert signal.side == "BUY"
        assert signal.price > 0

    def test_signal_sell(self):
        signal = make_signal(side="SELL")
        assert signal.side == "SELL"

    def test_signal_shares_calculation(self):
        """Verify shares = net_amount / price."""
        signal = make_signal(price=0.34)
        from bot.services.fees import calculate_fee
        fee = calculate_fee(45.0)
        shares = fee.net_amount / signal.price
        assert shares == pytest.approx(131.03, abs=0.1)
