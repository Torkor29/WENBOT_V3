"""Example strategy – generates fake signals every 5 minutes.

This is a minimal reference implementation showing how a strategy pod
publishes signals to Redis so that the executor can pick them up.
There is NO real trading logic here; it is purely illustrative.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import redis.asyncio as aioredis

from shared.config import REDIS_URL

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
STRATEGY_ID = "strat_example_v1"
CHANNEL = f"signals:{STRATEGY_ID}"
INTERVAL_SECONDS = 5 * 60  # every 5 minutes

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(STRATEGY_ID)


async def publish_signal(redis_client: aioredis.Redis) -> dict:
    """Build a fictitious signal and publish it on the Redis channel."""

    signal = {
        "strategy_id": STRATEGY_ID,
        "action": "BUY",
        "side": random.choice(["YES", "NO"]),
        "market_slug": "btc-updown-5m-example",
        "token_id": "example_token_id_placeholder",
        "max_price": round(random.uniform(0.40, 0.70), 2),
        "confidence": round(random.uniform(0.5, 0.95), 2),
        "timestamp": time.time(),
    }

    payload = json.dumps(signal)
    await redis_client.publish(CHANNEL, payload)
    logger.info("Published signal on %s: %s", CHANNEL, payload)
    return signal


async def main() -> None:
    """Connect to Redis and emit a fake signal every 5 minutes."""

    logger.info("Starting example strategy (%s) ...", STRATEGY_ID)

    redis_client = aioredis.from_url(
        REDIS_URL,
        decode_responses=True,
        max_connections=5,
    )

    # Verify connectivity
    await redis_client.ping()
    logger.info("Connected to Redis at %s", REDIS_URL)

    try:
        while True:
            await publish_signal(redis_client)
            await asyncio.sleep(INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Strategy loop cancelled, shutting down.")
    finally:
        await redis_client.aclose()
        logger.info("Redis connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
