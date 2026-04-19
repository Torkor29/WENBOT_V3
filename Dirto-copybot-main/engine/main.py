"""Execution engine entry point.

Subscribes to Redis ``signals:*`` channels and dispatches trade execution
for each active subscriber of the emitting strategy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from shared.models import Signal
from shared.redis_client import get_redis
from shared.supabase_client import get_supabase

from engine.fee_queue import execute_for_subscribers
from engine.perf_fee_cron import daily_perf_fee_job
from engine.resolver import resolver_loop

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


def _parse_signal(raw: str) -> Signal:
    """Parse a JSON string into a Signal dataclass."""
    data = json.loads(raw)
    return Signal(
        strategy_id=data["strategy_id"],
        action=data["action"],
        side=data["side"],
        market_slug=data["market_slug"],
        token_id=data["token_id"],
        max_price=float(data["max_price"]),
        shares=float(data.get("shares", 0.0)),
        confidence=float(data.get("confidence", 0.0)),
        timestamp=float(data.get("timestamp", 0)),
    )


def _log_signal_to_db(signal: Signal) -> None:
    """Insert the raw signal into the strategy_signals table for auditing."""
    sb = get_supabase()
    sb.table("strategy_signals").insert(
        {
            "strategy_id": signal.strategy_id,
            "action": signal.action,
            "side": signal.side,
            "market_slug": signal.market_slug,
            "token_id": signal.token_id,
            "max_price": signal.max_price,
            "confidence": signal.confidence,
            "signal_timestamp": signal.timestamp,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


def _get_active_subscribers(strategy_id: str) -> list[dict]:
    """Fetch active subscribers for a given strategy from Supabase."""
    sb = get_supabase()
    result = (
        sb.table("subscriptions")
        .select("user_id, trade_size")
        .eq("strategy_id", strategy_id)
        .eq("is_active", True)
        .execute()
    )
    return result.data or []


async def _handle_signal(raw_message: str) -> None:
    """Parse, log, and execute a signal."""
    try:
        signal = _parse_signal(raw_message)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse signal: %s error=%s", raw_message[:200], exc)
        return

    logger.info(
        "Signal received: strategy=%s action=%s market=%s side=%s price=%.4f",
        signal.strategy_id,
        signal.action,
        signal.market_slug,
        signal.side,
        signal.max_price,
    )

    # Log signal to DB
    try:
        _log_signal_to_db(signal)
    except Exception:
        logger.exception("Failed to log signal to DB")

    # Fetch active subscribers
    subscribers = _get_active_subscribers(signal.strategy_id)
    if not subscribers:
        logger.info("No active subscribers for strategy=%s", signal.strategy_id)
        return

    logger.info(
        "Executing for %d subscribers: strategy=%s",
        len(subscribers),
        signal.strategy_id,
    )

    await execute_for_subscribers(signal, subscribers)


async def _subscribe_and_listen() -> None:
    """Subscribe to Redis signals:* channels and process messages."""
    redis = await get_redis()
    pubsub = redis.pubsub()

    await pubsub.psubscribe("signals:*")
    logger.info("Subscribed to Redis pattern 'signals:*'")

    async for message in pubsub.listen():
        if message["type"] == "pmessage":
            raw_data = message["data"]
            asyncio.create_task(_handle_signal(raw_data))


async def main() -> None:
    """Start the execution engine with all background tasks."""
    logger.info("Execution engine starting")

    # Launch background tasks
    perf_fee_task = asyncio.create_task(daily_perf_fee_job())
    resolver_task = asyncio.create_task(resolver_loop())

    # Main listener
    listener_task = asyncio.create_task(_subscribe_and_listen())

    logger.info("All engine tasks started")

    # Wait for all tasks (they run forever)
    await asyncio.gather(listener_task, perf_fee_task, resolver_task)


if __name__ == "__main__":
    asyncio.run(main())
