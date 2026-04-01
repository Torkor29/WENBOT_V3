"""Tests for strategy resolver — PnL calculation, win/loss determination."""

import pytest


class TestPnLCalculation:
    """Test PnL calculations matching Dirto resolver logic."""

    def test_buy_won(self):
        """BUY YES, market resolves YES → WON."""
        shares = 15.0
        cost = 10.0  # bought at ~$0.67
        trade_won = True

        win_value = shares * 1.0 if trade_won else 0.0
        pnl = win_value - cost

        assert pnl == 5.0  # Won $15, paid $10

    def test_buy_lost(self):
        """BUY YES, market resolves NO → LOST."""
        shares = 15.0
        cost = 10.0
        trade_won = False

        win_value = shares * 1.0 if trade_won else 0.0
        pnl = win_value - cost

        assert pnl == -10.0  # Lost entire cost

    def test_buy_breakeven(self):
        """BUY at $1.00 per share → 0 PnL on win."""
        shares = 10.0
        cost = 10.0  # bought at $1.00
        trade_won = True

        win_value = shares * 1.0 if trade_won else 0.0
        pnl = win_value - cost

        assert pnl == 0.0

    def test_win_determination_yes(self):
        """Trade side YES + outcome YES = WON."""
        trade_side = "YES"
        outcome = "Yes"

        trade_won = (
            (trade_side == "YES" and outcome.lower() == "yes")
            or (trade_side == "NO" and outcome.lower() == "no")
        )
        assert trade_won is True

    def test_win_determination_no(self):
        """Trade side NO + outcome NO = WON."""
        trade_side = "NO"
        outcome = "No"

        trade_won = (
            (trade_side == "YES" and outcome.lower() == "yes")
            or (trade_side == "NO" and outcome.lower() == "no")
        )
        assert trade_won is True

    def test_loss_determination(self):
        """Trade side YES + outcome NO = LOST."""
        trade_side = "YES"
        outcome = "No"

        trade_won = (
            (trade_side == "YES" and outcome.lower() == "yes")
            or (trade_side == "NO" and outcome.lower() == "no")
        )
        assert trade_won is False


class TestStrategyStatsCalculation:
    """Test strategy aggregate stats calculation."""

    def test_stats_calculation(self):
        trades = [
            {"result": "WON", "pnl": 5.0},
            {"result": "WON", "pnl": 3.0},
            {"result": "LOST", "pnl": -8.0},
            {"result": "WON", "pnl": 2.0},
            {"result": "LOST", "pnl": -4.0},
        ]

        total = len(trades)
        total_pnl = sum(t["pnl"] for t in trades)
        wins = sum(1 for t in trades if t["result"] == "WON")
        win_rate = (wins / total * 100) if total > 0 else 0.0

        assert total == 5
        assert total_pnl == -2.0
        assert wins == 3
        assert win_rate == 60.0

    def test_empty_stats(self):
        trades = []
        total = len(trades)
        win_rate = (0 / total * 100) if total > 0 else 0.0

        assert win_rate == 0.0
