"""Tests for engine/fee_queue.py."""

from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from shared.models import Signal
from engine.fee_queue import execute_for_subscribers


def _make_signal() -> Signal:
    return Signal(
        strategy_id="strat-1",
        action="BUY",
        side="YES",
        market_slug="test-market",
        token_id="tok-1",
        max_price=0.60,
        confidence=0.8,
        timestamp=1700000000.0,
    )


def _make_user_row(
    user_id: str,
    fee_rate: float = 0.01,
    trades_today: int = 0,
    max_trades: int = 50,
) -> dict:
    return {
        "id": user_id,
        "created_at": "2024-01-01T00:00:00+00:00",
        "telegram_id": 12345,
        "telegram_username": "testuser",
        "wallet_address": f"0xWallet{user_id}",
        "encrypted_private_key": "encrypted_blob",
        "trade_fee_rate": fee_rate,
        "is_active": True,
        "max_trade_size": 10.0,
        "max_trades_per_day": max_trades,
        "is_paused": False,
        "matic_refills_count": 0,
        "matic_total_sent": 0.0,
        "last_matic_refill_at": None,
        "trades_today": trades_today,
        "trades_today_reset_at": date.today().isoformat(),
    }


class TestFeeQueuePriority(unittest.TestCase):
    """Test that subscribers are executed in fee-rate descending order."""

    @patch("engine.fee_queue.check_and_refill_matic", new_callable=AsyncMock)
    @patch("engine.fee_queue.execute_trade_for_user", new_callable=AsyncMock)
    @patch("engine.fee_queue.get_usdc_balance")
    @patch("engine.fee_queue.get_supabase")
    def test_priority_order(
        self,
        mock_sb_factory,
        mock_usdc,
        mock_execute,
        mock_matic,
    ):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        user_a = _make_user_row("A", fee_rate=0.05)
        user_b = _make_user_row("B", fee_rate=0.02)
        user_c = _make_user_row("C", fee_rate=0.10)

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_in = MagicMock()
        mock_select.in_.return_value = mock_in
        mock_in.execute.return_value = MagicMock(data=[user_a, user_b, user_c])

        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_eq.execute.return_value = MagicMock(
            data=[{"execution_delay_ms": 0}]
        )

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        mock_usdc.return_value = 100.0
        mock_execute.return_value = "trade-1"
        mock_matic.return_value = True

        subscribers = [
            {"user_id": "A", "trade_size": 4.0},
            {"user_id": "B", "trade_size": 4.0},
            {"user_id": "C", "trade_size": 4.0},
        ]

        asyncio.run(execute_for_subscribers(_make_signal(), subscribers))

        # Check all 3 users were executed
        self.assertEqual(mock_execute.call_count, 3)

        # Check execution order: C (0.10) -> A (0.05) -> B (0.02)
        calls = mock_execute.call_args_list
        user_order = [c.kwargs["user"].id for c in calls]
        self.assertEqual(user_order, ["C", "A", "B"])


class TestFeeQueueInsufficientBalance(unittest.TestCase):
    """Test that users with insufficient balance are skipped."""

    @patch("engine.fee_queue.check_and_refill_matic", new_callable=AsyncMock)
    @patch("engine.fee_queue.execute_trade_for_user", new_callable=AsyncMock)
    @patch("engine.fee_queue.get_usdc_balance")
    @patch("engine.fee_queue.get_supabase")
    def test_skip_insufficient_balance(
        self, mock_sb_factory, mock_usdc, mock_execute, mock_matic
    ):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        user_row = _make_user_row("U1", fee_rate=0.02)

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_in = MagicMock()
        mock_select.in_.return_value = mock_in
        mock_in.execute.return_value = MagicMock(data=[user_row])

        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_eq.execute.return_value = MagicMock(
            data=[{"execution_delay_ms": 0}]
        )

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        # Balance too low for trade size
        mock_usdc.return_value = 1.0
        mock_matic.return_value = True

        subscribers = [{"user_id": "U1", "trade_size": 4.0}]

        asyncio.run(execute_for_subscribers(_make_signal(), subscribers))

        # Should NOT have called execute_trade_for_user (skipped)
        mock_execute.assert_not_called()


class TestFeeQueueDailyLimit(unittest.TestCase):
    """Test that users at their daily trade limit are skipped."""

    @patch("engine.fee_queue.execute_trade_for_user", new_callable=AsyncMock)
    @patch("engine.fee_queue.get_usdc_balance")
    @patch("engine.fee_queue.get_supabase")
    def test_skip_daily_limit(self, mock_sb_factory, mock_usdc, mock_execute):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        user_row = _make_user_row("U1", fee_rate=0.02, trades_today=50, max_trades=50)

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_in = MagicMock()
        mock_select.in_.return_value = mock_in
        mock_in.execute.return_value = MagicMock(data=[user_row])

        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_eq.execute.return_value = MagicMock(
            data=[{"execution_delay_ms": 0}]
        )

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        mock_usdc.return_value = 100.0

        subscribers = [{"user_id": "U1", "trade_size": 4.0}]

        asyncio.run(execute_for_subscribers(_make_signal(), subscribers))

        # Should NOT have called execute (daily limit reached)
        mock_execute.assert_not_called()


class TestMinFeeRateEnforcement(unittest.TestCase):
    """Test that the minimum fee rate is enforced inside executor (not fee_queue anymore)."""

    @patch("engine.fee_queue.check_and_refill_matic", new_callable=AsyncMock)
    @patch("engine.fee_queue.execute_trade_for_user", new_callable=AsyncMock)
    @patch("engine.fee_queue.get_usdc_balance")
    @patch("engine.fee_queue.get_supabase")
    def test_low_fee_user_still_executed(
        self, mock_sb_factory, mock_usdc, mock_execute, mock_matic
    ):
        """Fee rate enforcement is now in executor.py, fee_queue just dispatches."""
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        user_row = _make_user_row("U1", fee_rate=0.001)

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_in = MagicMock()
        mock_select.in_.return_value = mock_in
        mock_in.execute.return_value = MagicMock(data=[user_row])

        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_eq.execute.return_value = MagicMock(
            data=[{"execution_delay_ms": 0}]
        )

        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        mock_usdc.return_value = 100.0
        mock_execute.return_value = "trade-1"
        mock_matic.return_value = True

        subscribers = [{"user_id": "U1", "trade_size": 4.0}]

        asyncio.run(execute_for_subscribers(_make_signal(), subscribers))

        # User should be executed (fee enforcement is in executor now)
        mock_execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
