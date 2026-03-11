"""Tests for circuit breaker service."""

import time
import pytest
from unittest.mock import patch

from bot.services.circuit_breaker import (
    CircuitBreaker,
    BreakerState,
    CircuitState,
)


class TestCircuitBreakerInit:
    def test_default_state_closed(self):
        cb = CircuitBreaker()
        assert cb.global_state.state == BreakerState.CLOSED

    def test_user_starts_closed(self):
        cb = CircuitBreaker()
        allowed, reason = cb.is_trading_allowed(user_id=1)
        assert allowed is True
        assert reason == ""


class TestUserBreaker:
    def test_success_resets_failures(self):
        cb = CircuitBreaker(max_consecutive_failures=3)
        cb.record_failure(1, "fail1")
        cb.record_failure(1, "fail2")
        assert cb.get_user_state(1).consecutive_failures == 2

        cb.record_success(1)
        assert cb.get_user_state(1).consecutive_failures == 0

    def test_trips_after_max_failures(self):
        cb = CircuitBreaker(max_consecutive_failures=3)
        cb.record_failure(1, "f1")
        cb.record_failure(1, "f2")
        cb.record_failure(1, "f3")

        state = cb.get_user_state(1)
        assert state.state == BreakerState.OPEN
        assert state.tripped_at is not None

    def test_blocks_after_trip(self):
        cb = CircuitBreaker(max_consecutive_failures=2, cooldown_seconds=3600)
        cb.record_failure(1)
        cb.record_failure(1)

        allowed, reason = cb.is_trading_allowed(1)
        assert allowed is False
        assert "Circuit breaker" in reason

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(max_consecutive_failures=2, cooldown_seconds=0.1)
        cb.record_failure(1)
        cb.record_failure(1)

        import time
        time.sleep(0.15)

        allowed, _ = cb.is_trading_allowed(1)
        assert allowed is True
        assert cb.get_user_state(1).state == BreakerState.HALF_OPEN

    def test_closes_on_success_after_half_open(self):
        cb = CircuitBreaker(max_consecutive_failures=2, cooldown_seconds=0.1)
        cb.record_failure(1)
        cb.record_failure(1)

        time.sleep(0.15)
        cb.is_trading_allowed(1)  # Transitions to HALF_OPEN
        cb.record_success(1)

        assert cb.get_user_state(1).state == BreakerState.CLOSED

    def test_manual_trip(self):
        cb = CircuitBreaker()
        cb.trip_user(1, "Manual stop")
        allowed, reason = cb.is_trading_allowed(1)
        assert allowed is False
        assert "Manual stop" in reason

    def test_reset_user(self):
        cb = CircuitBreaker(max_consecutive_failures=2)
        cb.record_failure(1)
        cb.record_failure(1)
        assert cb.get_user_state(1).state == BreakerState.OPEN

        cb.reset_user(1)
        allowed, _ = cb.is_trading_allowed(1)
        assert allowed is True

    def test_independent_users(self):
        cb = CircuitBreaker(max_consecutive_failures=2)
        cb.record_failure(1)
        cb.record_failure(1)

        allowed_1, _ = cb.is_trading_allowed(1)
        allowed_2, _ = cb.is_trading_allowed(2)
        assert allowed_1 is False
        assert allowed_2 is True


class TestGlobalBreaker:
    def test_global_trip_blocks_all(self):
        cb = CircuitBreaker(cooldown_seconds=3600)
        cb.trip_global("Market crash detected")

        allowed_1, reason = cb.is_trading_allowed(1)
        assert allowed_1 is False
        assert "Global" in reason

        allowed_2, _ = cb.is_trading_allowed(2)
        assert allowed_2 is False

    def test_global_reset(self):
        cb = CircuitBreaker()
        cb.trip_global("Emergency")
        cb.reset_global()

        allowed, _ = cb.is_trading_allowed(1)
        assert allowed is True

    def test_global_half_open_after_cooldown(self):
        cb = CircuitBreaker(cooldown_seconds=0.1)
        cb.trip_global("Test")

        time.sleep(0.15)

        allowed, _ = cb.is_trading_allowed(1)
        assert allowed is True
        assert cb.global_state.state == BreakerState.HALF_OPEN


class TestCircuitState:
    def test_default_state(self):
        state = CircuitState()
        assert state.state == BreakerState.CLOSED
        assert state.consecutive_failures == 0
        assert state.tripped_at is None

    def test_enum_values(self):
        assert BreakerState.CLOSED == "closed"
        assert BreakerState.OPEN == "open"
        assert BreakerState.HALF_OPEN == "half_open"
