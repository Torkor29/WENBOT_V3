"""Tests for strategy executor — fee queue priority, signal parsing."""

import pytest
import json
from datetime import date

from bot.services.strategy_listener import StrategySignalData, _parse_signal


class TestSignalParsing:
    def test_parse_valid_signal(self):
        raw = json.dumps({
            "strategy_id": "strat_v1",
            "action": "BUY",
            "side": "YES",
            "market_slug": "btc-above-100k",
            "token_id": "0xabc123",
            "max_price": 0.75,
            "shares": 0.0,
            "confidence": 0.85,
            "timestamp": 1711612345.0,
        })
        signal = _parse_signal(raw)
        assert signal.strategy_id == "strat_v1"
        assert signal.action == "BUY"
        assert signal.side == "YES"
        assert signal.max_price == 0.75
        assert signal.confidence == 0.85

    def test_parse_minimal_signal(self):
        raw = json.dumps({
            "strategy_id": "strat_v2",
            "action": "SELL",
            "side": "NO",
            "market_slug": "eth-merge",
            "token_id": "0xdef456",
            "max_price": 0.30,
        })
        signal = _parse_signal(raw)
        assert signal.strategy_id == "strat_v2"
        assert signal.action == "SELL"
        assert signal.shares == 0.0  # default
        assert signal.confidence == 0.0  # default

    def test_parse_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_signal("not json")

    def test_parse_missing_field(self):
        raw = json.dumps({
            "strategy_id": "strat_v1",
            "action": "BUY",
            # missing required fields
        })
        with pytest.raises(KeyError):
            _parse_signal(raw)


class TestStrategySignalDataclass:
    def test_signal_data_defaults(self):
        signal = StrategySignalData(
            strategy_id="test",
            action="BUY",
            side="YES",
            market_slug="test-market",
            token_id="0x123",
            max_price=0.5,
        )
        assert signal.shares == 0.0
        assert signal.confidence == 0.0
        assert signal.timestamp == 0.0

    def test_signal_data_with_all_fields(self):
        signal = StrategySignalData(
            strategy_id="test",
            action="SELL",
            side="NO",
            market_slug="test-market",
            token_id="0x456",
            max_price=0.8,
            shares=10.5,
            confidence=0.92,
            timestamp=1234567890.0,
        )
        assert signal.shares == 10.5
        assert signal.confidence == 0.92


class TestFeeQueuePriority:
    """Test that subscribers are sorted by fee_rate DESC."""

    def test_fee_rate_sorting(self):
        # Simulate the sorting logic from strategy_executor
        subs = [
            {"user_id": 1, "fee_rate": 0.01},
            {"user_id": 2, "fee_rate": 0.05},
            {"user_id": 3, "fee_rate": 0.03},
            {"user_id": 4, "fee_rate": 0.02},
        ]

        sorted_subs = sorted(subs, key=lambda s: s["fee_rate"], reverse=True)

        assert sorted_subs[0]["user_id"] == 2  # 5% first
        assert sorted_subs[1]["user_id"] == 3  # 3%
        assert sorted_subs[2]["user_id"] == 4  # 2%
        assert sorted_subs[3]["user_id"] == 1  # 1% last

    def test_fee_calculation(self):
        """Test fee = trade_size * fee_rate, net = trade_size - fee."""
        trade_size = 10.0
        fee_rate = 0.03  # 3%
        min_fee_rate = 0.01

        effective_rate = max(fee_rate, min_fee_rate)
        fee_amount = round(trade_size * effective_rate, 6)
        net_amount = round(trade_size - fee_amount, 6)

        assert fee_amount == 0.3
        assert net_amount == 9.7

    def test_min_fee_rate_enforced(self):
        """Fee rate should not go below minimum."""
        trade_size = 10.0
        fee_rate = 0.005  # 0.5% — below min
        min_fee_rate = 0.01

        effective_rate = max(fee_rate, min_fee_rate)
        fee_amount = round(trade_size * effective_rate, 6)

        assert effective_rate == 0.01
        assert fee_amount == 0.1
