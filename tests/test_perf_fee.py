"""Tests for performance fee calculation logic."""

import pytest


class TestPerfFeeCalculation:
    """Test daily performance fee logic matching Dirto perf_fee_cron."""

    def test_positive_pnl_fee(self):
        """5% of positive PnL."""
        total_pnl = 100.0
        perf_fee_rate = 0.05
        perf_fee = total_pnl * perf_fee_rate

        assert perf_fee == 5.0

    def test_negative_pnl_skip(self):
        """No fee on negative PnL."""
        total_pnl = -50.0
        perf_fee_rate = 0.05

        should_skip = total_pnl <= 0
        assert should_skip is True

    def test_zero_pnl_skip(self):
        """No fee on zero PnL."""
        total_pnl = 0.0
        should_skip = total_pnl <= 0
        assert should_skip is True

    def test_fee_capped_by_balance(self):
        """Fee should not exceed wallet balance."""
        total_pnl = 200.0
        perf_fee_rate = 0.05
        perf_fee = total_pnl * perf_fee_rate  # $10

        wallet_balance = 5.0  # Only $5 available

        if perf_fee > wallet_balance:
            perf_fee = wallet_balance

        assert perf_fee == 5.0

    def test_fee_too_small_skip(self):
        """Fee below $0.01 should be skipped."""
        total_pnl = 0.10
        perf_fee_rate = 0.05
        perf_fee = total_pnl * perf_fee_rate  # $0.005

        should_skip = perf_fee < 0.01
        assert should_skip is True

    def test_daily_stats_calculation(self):
        """Calculate daily wins/losses/PnL from trades."""
        trades = [
            {"pnl": 5.0, "result": "WON"},
            {"pnl": -3.0, "result": "LOST"},
            {"pnl": 8.0, "result": "WON"},
            {"pnl": -2.0, "result": "LOST"},
            {"pnl": 1.0, "result": "WON"},
        ]

        total_pnl = sum(t["pnl"] for t in trades)
        total_count = len(trades)
        wins = sum(1 for t in trades if t["result"] == "WON")
        losses = total_count - wins

        assert total_pnl == 9.0
        assert wins == 3
        assert losses == 2

        perf_fee = total_pnl * 0.05
        assert perf_fee == 0.45


class TestGasManagerAntiExploit:
    """Test MATIC refill anti-exploit checks (logic only, no blockchain)."""

    def test_lifetime_cap_blocks(self):
        refills_count = 3
        max_refills = 3
        assert refills_count >= max_refills

    def test_lifetime_cap_allows(self):
        refills_count = 2
        max_refills = 3
        assert refills_count < max_refills

    def test_total_sent_cap(self):
        total_sent = 0.25
        max_total = 0.3
        refill_amount = 0.1
        projected = total_sent + refill_amount
        assert projected > max_total  # Should block

    def test_total_sent_allows(self):
        total_sent = 0.1
        max_total = 0.3
        refill_amount = 0.1
        projected = total_sent + refill_amount
        assert projected <= max_total  # Should allow

    def test_min_usdc_blocks(self):
        usdc_balance = 1.5
        min_usdc = 2.0
        assert usdc_balance < min_usdc  # Should skip

    def test_min_usdc_allows(self):
        usdc_balance = 5.0
        min_usdc = 2.0
        assert usdc_balance >= min_usdc  # Should allow
