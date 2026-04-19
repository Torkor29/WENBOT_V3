"""Tests for engine/executor.py."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from shared.models import Signal, User
from engine.executor import (
    execute_trade_for_user,
    send_trade_fee,
    _insert_trade,
)


def _make_user(**overrides) -> User:
    defaults = dict(
        id="user-1",
        created_at=datetime.now(timezone.utc),
        telegram_id=123,
        telegram_username="testuser",
        wallet_address="0xWallet",
        encrypted_private_key="encrypted_pk",
        trade_fee_rate=0.01,
    )
    defaults.update(overrides)
    return User(**defaults)


def _make_signal(**overrides) -> Signal:
    defaults = dict(
        strategy_id="strat-1",
        action="BUY",
        side="YES",
        market_slug="will-it-rain",
        token_id="token-xyz",
        max_price=0.65,
    )
    defaults.update(overrides)
    return Signal(**defaults)


class TestExecuteTradeForUserBuy(unittest.TestCase):
    """Tests for BUY flow in execute_trade_for_user."""

    @patch("engine.executor._insert_trade", return_value="trade-1")
    @patch("engine.executor.place_buy_order")
    @patch("engine.executor.send_trade_fee")
    @patch("engine.executor.decrypt", return_value="0xfake_pk")
    def test_buy_success(self, mock_decrypt, mock_fee, mock_buy, mock_insert):
        mock_fee.return_value = "0xtxhash"
        mock_buy.return_value = {
            "success": True,
            "partial": False,
            "status": "FULL_SUCCESS",
            "order_id": "order-1",
            "shares": 10.0,
            "cost": 3.5,
            "entry_price": 0.35,
        }

        user = _make_user()
        signal = _make_signal()

        result = asyncio.get_event_loop().run_until_complete(
            execute_trade_for_user(user, signal, trade_size=4.0, priority=0)
        )

        self.assertEqual(result, "trade-1")
        mock_decrypt.assert_called_once()
        mock_fee.assert_called_once()
        mock_buy.assert_called_once()
        mock_insert.assert_called_once()
        # Check status is PLACED
        call_kwargs = mock_insert.call_args[1]
        self.assertEqual(call_kwargs["status"], "PLACED")

    @patch("engine.executor._insert_trade", return_value="trade-fail")
    @patch("engine.executor.send_trade_fee", return_value=None)
    @patch("engine.executor.decrypt", return_value="0xfake_pk")
    def test_buy_fee_failure_aborts(self, mock_decrypt, mock_fee, mock_insert):
        user = _make_user()
        signal = _make_signal()

        result = asyncio.get_event_loop().run_until_complete(
            execute_trade_for_user(user, signal, trade_size=4.0, priority=0)
        )

        self.assertEqual(result, "trade-fail")
        # Should insert as FAILED
        call_kwargs = mock_insert.call_args[1]
        self.assertEqual(call_kwargs["status"], "FAILED")


class TestExecuteTradeForUserSell(unittest.TestCase):
    """Tests for SELL flow in execute_trade_for_user."""

    @patch("engine.executor._insert_trade", return_value="trade-sell-1")
    @patch("engine.executor.place_sell_order")
    @patch("engine.executor.decrypt", return_value="0xfake_pk")
    def test_sell_no_fee(self, mock_decrypt, mock_sell, mock_insert):
        mock_sell.return_value = {
            "success": True,
            "partial": False,
            "status": "FULL_SUCCESS",
            "order_id": "order-sell-1",
            "sold": 8.0,
            "remaining": 0.0,
            "received": 5.5,
        }

        user = _make_user()
        signal = _make_signal(action="SELL", shares=8.0)

        result = asyncio.get_event_loop().run_until_complete(
            execute_trade_for_user(user, signal, trade_size=4.0, priority=0)
        )

        self.assertEqual(result, "trade-sell-1")
        mock_sell.assert_called_once_with(
            private_key="0xfake_pk",
            token_id="token-xyz",
            shares=8.0,
        )
        # No fee on SELL
        call_kwargs = mock_insert.call_args[1]
        self.assertEqual(call_kwargs["fee_info"]["fee_amount"], 0)


class TestSendTradeFee(unittest.TestCase):
    """Tests for the send_trade_fee helper."""

    @patch("engine.executor.WENBOT_FEE_WALLET", "0xFeeWallet")
    @patch("engine.executor.send_usdc_transfer")
    def test_send_fee_calls_transfer(self, mock_transfer):
        mock_transfer.return_value = "0xtxhash123"

        tx = asyncio.get_event_loop().run_until_complete(
            send_trade_fee("0xprivkey", 0.50)
        )

        self.assertEqual(tx, "0xtxhash123")

    @patch("engine.executor.WENBOT_FEE_WALLET", "")
    def test_send_fee_returns_none_if_no_wallet(self):
        tx = asyncio.get_event_loop().run_until_complete(
            send_trade_fee("0xprivkey", 0.50)
        )

        self.assertIsNone(tx)


class TestInsertTrade(unittest.TestCase):
    """Tests for the _insert_trade helper."""

    @patch("engine.executor.get_supabase")
    def test_insert_trade_creates_row(self, mock_sb_factory):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock(data=[{"id": "trade-999"}])

        signal = _make_signal()

        trade_id = _insert_trade(
            user_id="user-1",
            strategy_id="strat-1",
            signal=signal,
            fee_info={"fee_rate": 0.02, "fee_amount": 0.08, "fee_tx_hash": "0xfee"},
            order_info={"trade_amount": 3.92, "order_id": "ord-1"},
            priority=0,
            status="PLACED",
        )

        self.assertEqual(trade_id, "trade-999")
        call_args = mock_table.insert.call_args[0][0]
        self.assertEqual(call_args["user_id"], "user-1")
        self.assertEqual(call_args["status"], "PLACED")


if __name__ == "__main__":
    unittest.main()
