"""Tests for engine/gas_manager.py."""

from __future__ import annotations

import asyncio
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from shared.models import User
from engine.gas_manager import check_and_refill_matic


def _make_user(**overrides) -> User:
    defaults = {
        "id": "user-1",
        "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "telegram_id": 12345,
        "telegram_username": "testuser",
        "wallet_address": "0xUserWallet",
        "encrypted_private_key": "enc_blob",
        "trade_fee_rate": 0.02,
        "is_active": True,
        "max_trade_size": 10.0,
        "max_trades_per_day": 50,
        "is_paused": False,
        "matic_refills_count": 0,
        "matic_total_sent": 0.0,
        "last_matic_refill_at": None,
        "trades_today": 0,
        "trades_today_reset_at": None,
    }
    defaults.update(overrides)
    return User(**defaults)


class TestMaticBalanceSufficient(unittest.TestCase):
    """If MATIC balance is already fine, no refill needed."""

    @patch("engine.gas_manager.get_matic_balance")
    def test_balance_ok_returns_true(self, mock_matic_bal):
        mock_matic_bal.return_value = 0.05  # Above 0.01 threshold
        user = _make_user()
        result = asyncio.run(check_and_refill_matic(user))
        self.assertTrue(result)


class TestLifetimeCapReached(unittest.TestCase):
    """CHECK 1: Lifetime refill cap blocks further refills."""

    @patch("engine.gas_manager.alert_admin", new_callable=AsyncMock)
    @patch("engine.gas_manager.get_matic_balance")
    def test_refill_count_cap(self, mock_matic_bal, mock_alert):
        mock_matic_bal.return_value = 0.001  # Low

        user = _make_user(matic_refills_count=3)  # At cap
        result = asyncio.run(check_and_refill_matic(user))
        self.assertFalse(result)

    @patch("engine.gas_manager.alert_admin", new_callable=AsyncMock)
    @patch("engine.gas_manager.get_matic_balance")
    def test_total_sent_cap(self, mock_matic_bal, mock_alert):
        mock_matic_bal.return_value = 0.001

        user = _make_user(matic_total_sent=0.3)  # At cap
        result = asyncio.run(check_and_refill_matic(user))
        self.assertFalse(result)


class TestUsdcMinimum(unittest.TestCase):
    """CHECK 2: Insufficient USDC blocks refill."""

    @patch("engine.gas_manager.get_usdc_balance")
    @patch("engine.gas_manager.get_matic_balance")
    def test_low_usdc_blocks_refill(self, mock_matic_bal, mock_usdc_bal):
        mock_matic_bal.return_value = 0.001  # Low MATIC
        mock_usdc_bal.return_value = 1.0  # Below 2.0 threshold

        user = _make_user()
        result = asyncio.run(check_and_refill_matic(user))
        self.assertFalse(result)


class TestRateLimit24h(unittest.TestCase):
    """CHECK 3: Rate limit of 1 refill per 24 hours."""

    @patch("engine.gas_manager.get_usdc_balance")
    @patch("engine.gas_manager.get_matic_balance")
    def test_recent_refill_blocks(self, mock_matic_bal, mock_usdc_bal):
        mock_matic_bal.return_value = 0.001
        mock_usdc_bal.return_value = 10.0

        # Last refill was 1 hour ago
        recent = datetime.fromtimestamp(time.time() - 3600, tz=timezone.utc)
        user = _make_user(last_matic_refill_at=recent)
        result = asyncio.run(check_and_refill_matic(user))
        self.assertFalse(result)


class TestSuccessfulRefill(unittest.TestCase):
    """All checks pass, refill should succeed."""

    @patch("engine.gas_manager.get_supabase")
    @patch("engine.gas_manager.send_matic_transfer")
    @patch("engine.gas_manager.get_usdc_balance")
    @patch("engine.gas_manager.get_matic_balance")
    def test_refill_succeeds(
        self, mock_matic_bal, mock_usdc_bal, mock_send, mock_sb_factory
    ):
        mock_matic_bal.return_value = 0.001  # Low
        mock_usdc_bal.return_value = 10.0  # Sufficient
        mock_send.return_value = "0xmatictx"

        mock_sb = MagicMock()
        mock_sb_factory.return_value = mock_sb
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_update = MagicMock()
        mock_table.update.return_value = mock_update
        mock_update.eq.return_value = mock_update
        mock_update.execute.return_value = MagicMock()

        user = _make_user()
        result = asyncio.run(check_and_refill_matic(user))

        self.assertTrue(result)
        mock_send.assert_called_once()
        # Verify counters updated
        mock_sb.table.assert_called_with("users")
        update_data = mock_table.update.call_args[0][0]
        self.assertEqual(update_data["matic_refills_count"], 1)
        self.assertAlmostEqual(update_data["matic_total_sent"], 0.1, places=4)


if __name__ == "__main__":
    unittest.main()
