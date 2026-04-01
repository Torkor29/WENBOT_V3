"""StrategyListener — subscribes to Redis signals:* and dispatches to executor.

Async service pattern (same as MultiMasterMonitor): start/stop/loop.
Ported from Dirto-copybot-main/engine/main.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

import redis.asyncio as aioredis

from bot.config import settings
from bot.db.session import async_session
from bot.models.strategy_signal import StrategySignal

logger = logging.getLogger(__name__)


# ── Signal dataclass (parsed from Redis JSON) ───────────────────────

@dataclass
class StrategySignalData:
    """Parsed signal from a strategy pod via Redis pub/sub."""
    strategy_id: str
    action: str          # BUY / SELL
    side: str            # YES / NO
    market_slug: str
    token_id: str
    max_price: float
    shares: float = 0.0
    confidence: float = 0.0
    timestamp: float = 0.0


def _parse_signal(raw: str) -> StrategySignalData:
    """Parse a JSON string into a StrategySignalData."""
    data = json.loads(raw)
    return StrategySignalData(
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


# ── Service ──────────────────────────────────────────────────────────

class StrategyListener:
    """Listens to Redis signals:* and dispatches parsed signals to executor."""

    def __init__(
        self,
        on_signal: Callable[[StrategySignalData], Coroutine[Any, Any, None]],
    ):
        self._on_signal = on_signal
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Connect to Redis and start listening."""
        self._redis = aioredis.from_url(
            settings.strategy_redis_url,
            decode_responses=True,
        )
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe("signals:*")
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("StrategyListener started — subscribed to signals:*")

    async def stop(self) -> None:
        """Gracefully shut down the listener."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.punsubscribe("signals:*")
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        logger.info("StrategyListener stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Internal ─────────────────────────────────────────────────────

    async def _listen_loop(self) -> None:
        """Main loop: read messages from Redis pub/sub."""
        while self._running:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "pmessage":
                    raw_data = message["data"]
                    asyncio.create_task(self._handle_message(raw_data))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in StrategyListener loop")
                await asyncio.sleep(5)

    async def _handle_message(self, raw_data: str) -> None:
        """Parse, log to DB, and dispatch a signal."""
        try:
            signal = _parse_signal(raw_data)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Failed to parse signal: %s error=%s", raw_data[:200], exc)
            return

        logger.info(
            "Signal received: strategy=%s action=%s market=%s side=%s price=%.4f",
            signal.strategy_id, signal.action, signal.market_slug,
            signal.side, signal.max_price,
        )

        # Log to strategy_signals table (audit trail)
        await self._log_signal(signal)

        # Dispatch to executor
        try:
            await self._on_signal(signal)
        except Exception:
            logger.exception("Error dispatching signal for strategy=%s", signal.strategy_id)

    async def _log_signal(self, signal: StrategySignalData) -> None:
        """Insert signal into strategy_signals table."""
        try:
            async with async_session() as session:
                record = StrategySignal(
                    strategy_id=signal.strategy_id,
                    action=signal.action,
                    side=signal.side,
                    market_slug=signal.market_slug,
                    token_id=signal.token_id,
                    max_price=signal.max_price,
                    shares=signal.shares,
                    confidence=signal.confidence,
                    signal_timestamp=signal.timestamp,
                )
                session.add(record)
                await session.commit()
        except Exception:
            logger.exception("Failed to log signal to DB")
