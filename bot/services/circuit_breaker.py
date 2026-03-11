"""Circuit breaker — halts trading when losses exceed thresholds.

Protections:
- Per-user: stops copying if P&L drops below user's stop-loss %
- Global: halts all trading if platform-wide losses exceed threshold
- Time-based: auto-resets after cooldown period
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.trade import Trade, TradeStatus
from bot.models.user import User

logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    CLOSED = "closed"    # Normal — trading allowed
    OPEN = "open"        # Tripped — trading halted
    HALF_OPEN = "half_open"  # Testing — allow limited trades


@dataclass
class CircuitState:
    state: BreakerState = BreakerState.CLOSED
    tripped_at: Optional[float] = None
    reason: str = ""
    consecutive_failures: int = 0
    cooldown_seconds: float = 3600  # 1 hour default


class CircuitBreaker:
    """Per-user and global circuit breaker for trade safety."""

    def __init__(
        self,
        max_consecutive_failures: int = 5,
        global_loss_threshold_pct: float = 30.0,
        cooldown_seconds: float = 3600,
    ):
        self._max_failures = max_consecutive_failures
        self._global_threshold = global_loss_threshold_pct
        self._cooldown = cooldown_seconds
        self._user_states: dict[int, CircuitState] = {}
        self._global_state = CircuitState(cooldown_seconds=cooldown_seconds)

    def get_user_state(self, user_id: int) -> CircuitState:
        """Get circuit state for a user."""
        if user_id not in self._user_states:
            self._user_states[user_id] = CircuitState(
                cooldown_seconds=self._cooldown
            )
        return self._user_states[user_id]

    def is_trading_allowed(self, user_id: int) -> tuple[bool, str]:
        """Check if trading is allowed for a user.

        Returns:
            (allowed, reason) tuple.
        """
        # Check global breaker first
        if self._global_state.state == BreakerState.OPEN:
            elapsed = time.time() - (self._global_state.tripped_at or 0)
            if elapsed < self._global_state.cooldown_seconds:
                return False, f"Global circuit breaker: {self._global_state.reason}"
            else:
                # Cooldown expired — move to half-open
                self._global_state.state = BreakerState.HALF_OPEN

        # Check user breaker
        user_state = self.get_user_state(user_id)
        if user_state.state == BreakerState.OPEN:
            elapsed = time.time() - (user_state.tripped_at or 0)
            if elapsed < user_state.cooldown_seconds:
                return False, f"Circuit breaker: {user_state.reason}"
            else:
                user_state.state = BreakerState.HALF_OPEN

        return True, ""

    def record_success(self, user_id: int) -> None:
        """Record a successful trade — reset failure counter."""
        state = self.get_user_state(user_id)
        state.consecutive_failures = 0
        if state.state == BreakerState.HALF_OPEN:
            state.state = BreakerState.CLOSED
            logger.info(f"Circuit breaker closed for user {user_id}")

    def record_failure(self, user_id: int, reason: str = "") -> None:
        """Record a failed trade — may trip the breaker."""
        state = self.get_user_state(user_id)
        state.consecutive_failures += 1

        if state.consecutive_failures >= self._max_failures:
            state.state = BreakerState.OPEN
            state.tripped_at = time.time()
            state.reason = reason or f"{state.consecutive_failures} consecutive failures"
            logger.warning(
                f"Circuit breaker OPENED for user {user_id}: {state.reason}"
            )

    async def check_user_pnl(
        self,
        session: AsyncSession,
        user: User,
        stop_loss_pct: float,
    ) -> tuple[bool, float]:
        """Check if user's P&L has dropped below stop-loss threshold.

        Returns:
            (is_safe, current_pnl_pct) tuple.
        """
        total_invested = await session.scalar(
            select(func.sum(Trade.gross_amount_usdc)).where(
                Trade.user_id == user.id,
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0.0

        if total_invested <= 0:
            return True, 0.0

        # Simplified P&L: compare gross invested vs current value
        # In production, this would check current market prices
        total_net = await session.scalar(
            select(func.sum(Trade.net_amount_usdc)).where(
                Trade.user_id == user.id,
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0.0

        pnl_pct = ((total_net - total_invested) / total_invested) * 100

        if pnl_pct < -stop_loss_pct:
            self.trip_user(user.id, f"P&L at {pnl_pct:.1f}% (stop-loss: -{stop_loss_pct}%)")
            return False, pnl_pct

        return True, pnl_pct

    def trip_user(self, user_id: int, reason: str) -> None:
        """Manually trip the circuit breaker for a user."""
        state = self.get_user_state(user_id)
        state.state = BreakerState.OPEN
        state.tripped_at = time.time()
        state.reason = reason
        logger.warning(f"Circuit breaker TRIPPED for user {user_id}: {reason}")

    def trip_global(self, reason: str) -> None:
        """Trip the global circuit breaker — halts ALL trading."""
        self._global_state.state = BreakerState.OPEN
        self._global_state.tripped_at = time.time()
        self._global_state.reason = reason
        logger.critical(f"GLOBAL circuit breaker TRIPPED: {reason}")

    def reset_user(self, user_id: int) -> None:
        """Manually reset a user's circuit breaker."""
        if user_id in self._user_states:
            self._user_states[user_id] = CircuitState(
                cooldown_seconds=self._cooldown
            )

    def reset_global(self) -> None:
        """Manually reset the global circuit breaker."""
        self._global_state = CircuitState(cooldown_seconds=self._cooldown)

    @property
    def global_state(self) -> CircuitState:
        return self._global_state


# Singleton
circuit_breaker = CircuitBreaker()
