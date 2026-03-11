"""Tests for position sizing engine."""

import pytest
from unittest.mock import MagicMock

from bot.models.settings import SizingMode
from bot.services.sizing import calculate_trade_size, SizingError


def make_settings(**overrides):
    """Create a mock UserSettings with defaults."""
    defaults = {
        "sizing_mode": SizingMode.FIXED,
        "fixed_amount": 10.0,
        "allocated_capital": 1000.0,
        "percent_per_trade": 5.0,
        "multiplier": 1.0,
        "min_trade_usdc": 1.0,
        "max_trade_usdc": 100.0,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestFixedSizing:
    def test_fixed_amount(self):
        s = make_settings(sizing_mode=SizingMode.FIXED, fixed_amount=25.0)
        result = calculate_trade_size(s, 100.0, 10000.0, 500.0)
        assert result == 25.0

    def test_fixed_capped_by_max(self):
        s = make_settings(sizing_mode=SizingMode.FIXED, fixed_amount=200.0)
        result = calculate_trade_size(s, 100.0, 10000.0, 500.0)
        assert result == 100.0  # max_trade_usdc

    def test_fixed_raised_to_min(self):
        s = make_settings(
            sizing_mode=SizingMode.FIXED, fixed_amount=0.5, min_trade_usdc=1.0
        )
        result = calculate_trade_size(s, 100.0, 10000.0, 500.0)
        assert result == 1.0  # min_trade_usdc


class TestPercentSizing:
    def test_percent_5_of_1000(self):
        s = make_settings(sizing_mode=SizingMode.PERCENT)
        result = calculate_trade_size(s, 100.0, 10000.0, 500.0)
        assert result == 50.0  # 5% of 1000

    def test_percent_capped_by_balance(self):
        s = make_settings(
            sizing_mode=SizingMode.PERCENT,
            percent_per_trade=50.0,
            max_trade_usdc=10000.0,
        )
        result = calculate_trade_size(s, 100.0, 10000.0, 200.0)
        assert result == 200.0  # capped by balance


class TestProportionalSizing:
    def test_proportional_basic(self):
        s = make_settings(
            sizing_mode=SizingMode.PROPORTIONAL,
            allocated_capital=5000.0,
            max_trade_usdc=10000.0,
        )
        # Master trades 100 out of 10000 (1%)
        result = calculate_trade_size(s, 100.0, 10000.0, 5000.0)
        assert result == 50.0  # 1% of 5000

    def test_proportional_zero_master_portfolio_raises(self):
        s = make_settings(sizing_mode=SizingMode.PROPORTIONAL)
        with pytest.raises(SizingError, match="positive"):
            calculate_trade_size(s, 100.0, 0.0, 500.0)


class TestMultiplier:
    def test_multiplier_2x(self):
        s = make_settings(
            sizing_mode=SizingMode.FIXED, fixed_amount=10.0, multiplier=2.0
        )
        result = calculate_trade_size(s, 100.0, 10000.0, 500.0)
        assert result == 20.0

    def test_multiplier_05x(self):
        s = make_settings(
            sizing_mode=SizingMode.FIXED, fixed_amount=10.0, multiplier=0.5
        )
        result = calculate_trade_size(s, 100.0, 10000.0, 500.0)
        assert result == 5.0


class TestBalanceConstraint:
    def test_balance_limits_trade(self):
        s = make_settings(
            sizing_mode=SizingMode.FIXED, fixed_amount=50.0
        )
        result = calculate_trade_size(s, 100.0, 10000.0, 30.0)
        assert result == 30.0

    def test_zero_balance_raises(self):
        s = make_settings(sizing_mode=SizingMode.FIXED, fixed_amount=10.0)
        with pytest.raises(SizingError, match="zero or negative"):
            calculate_trade_size(s, 100.0, 10000.0, 0.0)
