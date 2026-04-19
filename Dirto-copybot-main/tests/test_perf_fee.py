"""Tests for engine/perf_fee_cron.py."""

from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from engine.perf_fee_cron import _process_user_perf_fee


def _make_user_row(user_id: str = "user-1", balance: float = 100.0) -> dict:
    return {
        "id": user_id,
        "wallet_address": "0xWallet1",
        "encrypted_private_key": "enc_blob",
        "is_active": True,
    }


class TestPerfFeePositivePnl(unittest.TestCase):
    """PnL positive: fee should be collected."""

    @patch("engine.perf_fee_cron.send_usdc_transfer")
    @patch("engine.perf_fee_cron.decrypt")
    @patch("engine.perf_fee_cron.get_usdc_balance")
    @patch("engine.perf_fee_cron.get_supabase")
    def test_positive_pnl_sends_fee(
        self, mock_sb_factory, mock_usdc, mock_decrypt, mock_transfer
    ):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table

        # Trades query: 2 winning trades
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_not = MagicMock()
        mock_eq.not_ = mock_not
        mock_is = MagicMock()
        mock_not.is_.return_value = mock_is
        mock_gte = MagicMock()
        mock_is.gte.return_value = mock_gte
        mock_lte = MagicMock()
        mock_gte.lte.return_value = mock_lte
        mock_lte.execute.return_value = MagicMock(
            data=[
                {"pnl": 5.0, "result": "WON"},
                {"pnl": 3.0, "result": "WON"},
            ]
        )

        # For not_ on table level
        mock_table.not_ = MagicMock()

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock()

        mock_usdc.return_value = 100.0
        mock_decrypt.return_value = "0xprivkey"
        mock_transfer.return_value = "0xperftx"

        user_row = _make_user_row()
        yesterday = date(2026, 3, 23)

        asyncio.run(_process_user_perf_fee(user_row, yesterday, "2026-03-23"))

        # Fee = (5+3) * 0.05 = 0.40
        mock_transfer.assert_called_once()
        call_args = mock_transfer.call_args
        self.assertAlmostEqual(call_args[1].get("amount_usdc", call_args[0][2] if len(call_args[0]) > 2 else None), 0.40, places=4)

        # Should insert with status SENT
        insert_data = mock_table.insert.call_args[0][0]
        self.assertEqual(insert_data["status"], "SENT")


class TestPerfFeeNegativePnl(unittest.TestCase):
    """PnL negative: fee should be SKIPPED."""

    @patch("engine.perf_fee_cron.get_supabase")
    def test_negative_pnl_skipped(self, mock_sb_factory):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_not = MagicMock()
        mock_eq.not_ = mock_not
        mock_is = MagicMock()
        mock_not.is_.return_value = mock_is
        mock_gte = MagicMock()
        mock_is.gte.return_value = mock_gte
        mock_lte = MagicMock()
        mock_gte.lte.return_value = mock_lte
        mock_lte.execute.return_value = MagicMock(
            data=[
                {"pnl": -2.0, "result": "LOST"},
                {"pnl": -3.0, "result": "LOST"},
            ]
        )

        mock_table.not_ = MagicMock()

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock()

        user_row = _make_user_row()
        yesterday = date(2026, 3, 23)

        asyncio.run(_process_user_perf_fee(user_row, yesterday, "2026-03-23"))

        insert_data = mock_table.insert.call_args[0][0]
        self.assertEqual(insert_data["status"], "SKIPPED")
        self.assertEqual(insert_data["perf_fee_amount"], 0)


class TestPerfFeeInsufficientBalance(unittest.TestCase):
    """PnL positive but balance insufficient: fee should be adjusted."""

    @patch("engine.perf_fee_cron.send_usdc_transfer")
    @patch("engine.perf_fee_cron.decrypt")
    @patch("engine.perf_fee_cron.get_usdc_balance")
    @patch("engine.perf_fee_cron.get_supabase")
    def test_adjusted_fee_on_low_balance(
        self, mock_sb_factory, mock_usdc, mock_decrypt, mock_transfer
    ):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_not = MagicMock()
        mock_eq.not_ = mock_not
        mock_is = MagicMock()
        mock_not.is_.return_value = mock_is
        mock_gte = MagicMock()
        mock_is.gte.return_value = mock_gte
        mock_lte = MagicMock()
        mock_gte.lte.return_value = mock_lte
        mock_lte.execute.return_value = MagicMock(
            data=[
                {"pnl": 100.0, "result": "WON"},
            ]
        )

        mock_table.not_ = MagicMock()

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock()

        # Fee would be 100 * 0.05 = 5.0, but balance is only 2.0
        mock_usdc.return_value = 2.0
        mock_decrypt.return_value = "0xprivkey"
        mock_transfer.return_value = "0xperftx"

        user_row = _make_user_row()
        yesterday = date(2026, 3, 23)

        asyncio.run(_process_user_perf_fee(user_row, yesterday, "2026-03-23"))

        # Fee should be adjusted to balance (2.0)
        call_args = mock_transfer.call_args
        actual_amount = call_args[1].get("amount_usdc", call_args[0][2] if len(call_args[0]) > 2 else None)
        self.assertAlmostEqual(actual_amount, 2.0, places=4)

        insert_data = mock_table.insert.call_args[0][0]
        self.assertEqual(insert_data["status"], "SENT")
        self.assertAlmostEqual(insert_data["perf_fee_amount"], 2.0, places=4)


class TestPerfFeeTooSmall(unittest.TestCase):
    """PnL positive but resulting fee is < 0.01: should be SKIPPED."""

    @patch("engine.perf_fee_cron.get_usdc_balance")
    @patch("engine.perf_fee_cron.get_supabase")
    def test_tiny_fee_skipped(self, mock_sb_factory, mock_usdc):
        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table

        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_not = MagicMock()
        mock_eq.not_ = mock_not
        mock_is = MagicMock()
        mock_not.is_.return_value = mock_is
        mock_gte = MagicMock()
        mock_is.gte.return_value = mock_gte
        mock_lte = MagicMock()
        mock_gte.lte.return_value = mock_lte
        mock_lte.execute.return_value = MagicMock(
            data=[
                {"pnl": 0.10, "result": "WON"},  # fee = 0.10 * 0.05 = 0.005
            ]
        )

        mock_table.not_ = MagicMock()

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock()

        mock_usdc.return_value = 100.0

        user_row = _make_user_row()
        yesterday = date(2026, 3, 23)

        asyncio.run(_process_user_perf_fee(user_row, yesterday, "2026-03-23"))

        insert_data = mock_table.insert.call_args[0][0]
        self.assertEqual(insert_data["status"], "SKIPPED")


if __name__ == "__main__":
    unittest.main()
