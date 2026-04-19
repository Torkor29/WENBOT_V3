"""Singleton async Redis client."""

from __future__ import annotations

from typing import Optional

import redis.asyncio as aioredis

from shared.config import REDIS_URL

_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Return a singleton async Redis client instance.

    The connection is lazily created on first call and reused afterwards.
    """
    global _client  # noqa: PLW0603
    if _client is None:
        _client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=10,
        )
    return _client
