"""Tests for rate limiter service."""

import time
import pytest

from bot.services.rate_limiter import RateLimiter, RateLimitResult, LIMITS


class TestRateLimiterMemory:
    """Test in-memory fallback rate limiter."""

    @pytest.mark.asyncio
    async def test_allows_under_limit(self):
        rl = RateLimiter()
        result = await rl.check("test:user1", max_requests=5, window_seconds=60)
        assert result.allowed is True
        assert result.remaining == 4
        assert result.limit == 5

    @pytest.mark.asyncio
    async def test_blocks_at_limit(self):
        rl = RateLimiter()
        for _ in range(5):
            await rl.check("test:user2", max_requests=5, window_seconds=60)

        result = await rl.check("test:user2", max_requests=5, window_seconds=60)
        assert result.allowed is False
        assert result.remaining == 0

    @pytest.mark.asyncio
    async def test_different_keys_independent(self):
        rl = RateLimiter()
        for _ in range(5):
            await rl.check("test:userA", max_requests=5, window_seconds=60)

        # Different key should not be affected
        result = await rl.check("test:userB", max_requests=5, window_seconds=60)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_window_expiry(self):
        rl = RateLimiter()
        # Fill up the limit
        for _ in range(3):
            await rl.check("test:expire", max_requests=3, window_seconds=1)

        # Should be blocked
        result = await rl.check("test:expire", max_requests=3, window_seconds=1)
        assert result.allowed is False

        # Wait for window to expire
        import asyncio
        await asyncio.sleep(1.1)

        # Should be allowed again
        result = await rl.check("test:expire", max_requests=3, window_seconds=1)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_remaining_decreases(self):
        rl = RateLimiter()
        r1 = await rl.check("test:dec", max_requests=3, window_seconds=60)
        assert r1.remaining == 2

        r2 = await rl.check("test:dec", max_requests=3, window_seconds=60)
        assert r2.remaining == 1

        r3 = await rl.check("test:dec", max_requests=3, window_seconds=60)
        assert r3.remaining == 0

    @pytest.mark.asyncio
    async def test_reset_key(self):
        rl = RateLimiter()
        for _ in range(5):
            await rl.check("test:reset", max_requests=5, window_seconds=60)

        # Should be blocked
        result = await rl.check("test:reset", max_requests=5, window_seconds=60)
        assert result.allowed is False

        # Reset
        rl.reset("test:reset")

        # Should be allowed again
        result = await rl.check("test:reset", max_requests=5, window_seconds=60)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_reset_in_seconds_positive(self):
        rl = RateLimiter()
        result = await rl.check("test:time", max_requests=5, window_seconds=60)
        assert result.reset_in_seconds > 0
        assert result.reset_in_seconds <= 60


class TestRateLimitResult:
    def test_result_creation(self):
        r = RateLimitResult(allowed=True, remaining=4, reset_in_seconds=55.0, limit=5)
        assert r.allowed
        assert r.remaining == 4
        assert r.limit == 5

    def test_blocked_result(self):
        r = RateLimitResult(allowed=False, remaining=0, reset_in_seconds=30.0, limit=10)
        assert not r.allowed


class TestLimitsConfig:
    def test_all_presets_exist(self):
        assert "command" in LIMITS
        assert "trade" in LIMITS
        assert "bridge" in LIMITS
        assert "admin" in LIMITS

    def test_presets_are_tuples(self):
        for key, val in LIMITS.items():
            assert isinstance(val, tuple)
            assert len(val) == 2
            assert val[0] > 0  # max_requests
            assert val[1] > 0  # window_seconds
