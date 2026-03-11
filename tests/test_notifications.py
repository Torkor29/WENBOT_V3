"""Tests for notification message formatting."""

import pytest
from unittest.mock import MagicMock

from bot.handlers.notifications import (
    format_trade_notification,
    format_trade_error,
    format_bridge_notification,
)
from bot.services.fees import FeeResult
from bot.models.trade import TradeSide


def make_trade(**overrides):
    """Create a mock Trade."""
    defaults = {
        "side": TradeSide.BUY,
        "price": 0.34,
        "shares": 131.03,
        "market_question": "Will Trump win in 2026 ?",
        "market_id": "market-001",
        "is_paper": False,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestTradeNotification:
    def test_buy_notification(self):
        trade = make_trade()
        fee = FeeResult(
            gross_amount=45.0, fee_rate=0.01, fee_amount=0.45,
            net_amount=44.55, fees_wallet="0xFees",
        )
        text = format_trade_notification(trade, fee, execution_time_s=1.2)
        assert "NOUVEAU TRADE COPIÉ" in text
        assert "YES" in text
        assert "45.00 USDC" in text
        assert "-0.45 USDC" in text
        assert "44.55 USDC" in text
        assert "1%" in text
        assert "1.2s" in text

    def test_sell_notification(self):
        trade = make_trade(side=TradeSide.SELL)
        fee = FeeResult(
            gross_amount=100.0, fee_rate=0.01, fee_amount=1.0,
            net_amount=99.0, fees_wallet="0xFees",
        )
        text = format_trade_notification(trade, fee)
        assert "🔴" in text
        assert "NO" in text

    def test_paper_trade_label(self):
        trade = make_trade(is_paper=True)
        fee = FeeResult(
            gross_amount=50.0, fee_rate=0.01, fee_amount=0.5,
            net_amount=49.5, fees_wallet="0xFees",
        )
        text = format_trade_notification(trade, fee)
        assert "PAPER" in text

    def test_bridge_used(self):
        trade = make_trade()
        fee = FeeResult(
            gross_amount=45.0, fee_rate=0.01, fee_amount=0.45,
            net_amount=44.55, fees_wallet="0xFees",
        )
        text = format_trade_notification(trade, fee, bridge_used=True)
        assert "Oui" in text

    def test_master_pnl_positive(self):
        trade = make_trade()
        fee = FeeResult(
            gross_amount=45.0, fee_rate=0.01, fee_amount=0.45,
            net_amount=44.55, fees_wallet="0xFees",
        )
        text = format_trade_notification(trade, fee, master_pnl=12.4)
        assert "+12.4%" in text

    def test_master_pnl_negative(self):
        trade = make_trade()
        fee = FeeResult(
            gross_amount=45.0, fee_rate=0.01, fee_amount=0.45,
            net_amount=44.55, fees_wallet="0xFees",
        )
        text = format_trade_notification(trade, fee, master_pnl=-5.3)
        assert "-5.3%" in text


class TestTradeError:
    def test_error_format(self):
        text = format_trade_error("Will BTC hit 100k?", "Insufficient USDC balance")
        assert "ERREUR" in text
        assert "Insufficient USDC balance" in text
        assert "/settings" in text


class TestBridgeNotification:
    def test_completed_bridge(self):
        text = format_bridge_notification(
            amount_sol=1.5,
            amount_usdc=150.25,
            bridge_provider="Li.Fi",
            fee_usd=0.5,
            tx_hash="0xabcdef1234567890abcdef1234567890abcdef12",
        )
        assert "BRIDGE SOL → USDC" in text
        assert "1.5000 SOL" in text
        assert "150.25 USDC" in text
        assert "Li.Fi" in text
        assert "✅" in text

    def test_pending_bridge(self):
        text = format_bridge_notification(
            amount_sol=2.0, amount_usdc=200.0,
            bridge_provider="Across", fee_usd=1.0,
            tx_hash="0x1234567890", status="pending",
        )
        assert "🟡" in text
        assert "pending" in text
