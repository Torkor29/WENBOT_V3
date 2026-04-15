"""Redis-based rate limiter for all bot actions.

Supports:
- Per-user rate limiting (commands, trades)
- Global rate limiting (API calls)
- Sliding window algorithm
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_in_seconds: float
    limit: int


class RateLimiter:
    """Redis sliding-window rate limiter.

    Falls back to in-memory dict if Redis is unavailable.
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._fallback: dict[str, list[float]] = {}

    async def check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> RateLimitResult:
        """Check if an action is allowed under rate limits.

        Args:
            key: Unique key (e.g., "user:12345:trade", "global:polymarket_api")
            max_requests: Maximum requests allowed in the window.
            window_seconds: Time window in seconds.

        Returns:
            RateLimitResult with allowed status and metadata.
        """
        if self._redis:
            return await self._check_redis(key, max_requests, window_seconds)
        return self._check_memory(key, max_requests, window_seconds)

    async def _check_redis(
        self, key: str, max_requests: int, window_seconds: int
    ) -> RateLimitResult:
        """Redis-based sliding window using sorted sets."""
        try:
            now = time.time()
            window_start = now - window_seconds
            pipe_key = f"ratelimit:{key}"

            pipe = self._redis.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(pipe_key, 0, window_start)
            # Count current entries
            pipe.zcard(pipe_key)
            # Add current request
            pipe.zadd(pipe_key, {str(now): now})
            # Set expiry on the key
            pipe.expire(pipe_key, window_seconds + 1)
            results = await pipe.execute()

            current_count = results[1]
            allowed = current_count < max_requests
            remaining = max(0, max_requests - current_count - (1 if allowed else 0))

            if not allowed:
                # Remove the entry we just added
                await self._redis.zrem(pipe_key, str(now))

            # Calculate reset time
            if not allowed:
                oldest = await self._redis.zrange(pipe_key, 0, 0, withscores=True)
                if oldest:
                    reset_in = oldest[0][1] + window_seconds - now
                else:
                    reset_in = float(window_seconds)
            else:
                reset_in = float(window_seconds)

            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_in_seconds=reset_in,
                limit=max_requests,
            )

        except Exception as e:
            logger.warning(f"Redis rate limit error, falling back to memory: {e}")
            return self._check_memory(key, max_requests, window_seconds)

    def _check_memory(
        self, key: str, max_requests: int, window_seconds: int
    ) -> RateLimitResult:
        """In-memory fallback rate limiter."""
        now = time.time()
        window_start = now - window_seconds

        if key not in self._fallback:
            self._fallback[key] = []

        # Remove expired timestamps
        self._fallback[key] = [
            ts for ts in self._fallback[key] if ts > window_start
        ]

        current_count = len(self._fallback[key])
        allowed = current_count < max_requests

        if allowed:
            self._fallback[key].append(now)
            remaining = max_requests - current_count - 1
        else:
            remaining = 0

        # Reset time
        if self._fallback[key]:
            oldest = min(self._fallback[key])
            reset_in = oldest + window_seconds - now
        else:
            reset_in = float(window_seconds)

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            reset_in_seconds=max(0, reset_in),
            limit=max_requests,
        )

    def reset(self, key: str) -> None:
        """Reset rate limit for a key (in-memory only)."""
        self._fallback.pop(key, None)


# Rate limit presets
LIMITS = {
    "command": (10, 60),         # 10 commands per minute per user
    "trade": (5, 60),            # 5 trades per minute per user
    "admin": (20, 60),           # 20 admin actions per minute
    "api_polymarket": (30, 60),  # 30 Polymarket API calls per minute
}


# Singleton — initialized without Redis, connected later
rate_limiter = RateLimiter()


async def init_rate_limiter(redis_url: str) -> RateLimiter:
    """Initialize rate limiter with Redis connection."""
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(redis_url, decode_responses=True)
        await client.ping()
        rate_limiter._redis = client
        logger.info("Rate limiter connected to Redis")
    except Exception as e:
        logger.warning(f"Redis unavailable, using in-memory rate limiter: {e}")
    return rate_limiter
