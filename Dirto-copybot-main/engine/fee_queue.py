"""Priority queue for trade execution, ordered by trade_fee_rate DESC."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from shared.models import Signal, User
from shared.supabase_client import get_supabase
from wallet.balance import get_usdc_balance

from engine.executor import execute_trade_for_user
from engine.gas_manager import check_and_refill_matic

logger = logging.getLogger(__name__)


def _parse_user(row: Dict[str, Any]) -> User:
    """Parse a Supabase user row into a User dataclass."""
    last_refill = row.get("last_matic_refill_at")
    if last_refill and isinstance(last_refill, str):
        last_refill = datetime.fromisoformat(last_refill.replace("Z", "+00:00"))

    reset_at = row.get("trades_today_reset_at")
    if reset_at and isinstance(reset_at, str):
        reset_at = date.fromisoformat(reset_at)

    return User(
        id=row["id"],
        created_at=datetime.fromisoformat(
            row.get("created_at", "2024-01-01T00:00:00+00:00").replace("Z", "+00:00")
        ),
        telegram_id=row.get("telegram_id", 0),
        telegram_username=row.get("telegram_username"),
        wallet_address=row["wallet_address"],
        encrypted_private_key=row["encrypted_private_key"],
        trade_fee_rate=row.get("trade_fee_rate", 0.01),
        is_active=row.get("is_active", True),
        max_trade_size=row.get("max_trade_size", 4.0),
        max_trades_per_day=row.get("max_trades_per_day", 50),
        is_paused=row.get("is_paused", False),
        matic_refills_count=row.get("matic_refills_count", 0),
        matic_total_sent=row.get("matic_total_sent", 0.0),
        last_matic_refill_at=last_refill,
        trades_today=row.get("trades_today", 0),
        trades_today_reset_at=reset_at,
    )


async def execute_for_subscribers(
    signal: Signal,
    subscribers: List[Dict[str, Any]],
) -> None:
    """Execute a trade signal for all subscribers in fee-priority order.

    Subscribers are sorted by trade_fee_rate descending so that higher-fee
    users get priority execution.  Each subscriber is processed sequentially
    with an execution delay between them.
    """
    if not subscribers:
        logger.info("No subscribers for signal strategy=%s", signal.strategy_id)
        return

    # Fetch user records for each subscriber
    sb = get_supabase()
    user_ids = [sub["user_id"] for sub in subscribers]
    users_result = sb.table("users").select("*").in_("id", user_ids).execute()

    if not users_result.data:
        logger.warning("No user records found for subscriber user_ids=%s", user_ids)
        return

    users_by_id: Dict[str, User] = {}
    for row in users_result.data:
        users_by_id[row["id"]] = _parse_user(row)

    # Build (subscriber, user) pairs and fetch strategy execution_delay_ms
    strategy_result = (
        sb.table("strategies")
        .select("execution_delay_ms")
        .eq("id", signal.strategy_id)
        .execute()
    )
    execution_delay_ms = 100
    if strategy_result.data:
        execution_delay_ms = strategy_result.data[0].get("execution_delay_ms", 100)

    # Sort by trade_fee_rate DESC
    sorted_subs = sorted(
        subscribers,
        key=lambda s: users_by_id.get(s["user_id"], User(id="", created_at=datetime.now(timezone.utc), telegram_id=0, telegram_username=None, wallet_address="", encrypted_private_key="")).trade_fee_rate,
        reverse=True,
    )

    for priority, sub in enumerate(sorted_subs):
        user_id = sub["user_id"]
        trade_size = sub.get("trade_size", 2.0)

        user = users_by_id.get(user_id)
        if user is None:
            logger.warning("User not found: user_id=%s, skipping", user_id)
            continue

        if user.is_paused:
            logger.info("User paused: user=%s, skipping", user_id)
            continue

        await _execute_single(
            signal=signal,
            user=user,
            trade_size=trade_size,
            priority=priority,
            strategy_id=signal.strategy_id,
        )

        # Delay between executions
        if execution_delay_ms > 0:
            await asyncio.sleep(execution_delay_ms / 1000.0)


async def _execute_single(
    signal: Signal,
    user: User,
    trade_size: float,
    priority: int,
    strategy_id: str,
) -> None:
    """Execute a signal for a single subscriber."""
    sb = get_supabase()
    today = date.today()

    # Reset daily trade counter if needed
    trades_today = user.trades_today
    if user.trades_today_reset_at != today:
        trades_today = 0
        sb.table("users").update(
            {"trades_today": 0, "trades_today_reset_at": today.isoformat()}
        ).eq("id", user.id).execute()

    # CHECK: Daily trade limit
    if trades_today >= user.max_trades_per_day:
        logger.info(
            "Daily limit reached: user=%s trades=%d/%d",
            user.id, trades_today, user.max_trades_per_day,
        )
        return

    # CHECK: USDC.e balance (only for BUY — SELL doesn't need USDC)
    if signal.action == "BUY":
        usdc_balance = get_usdc_balance(user.wallet_address)
        if usdc_balance < trade_size:
            logger.info(
                "Insufficient USDC balance: user=%s balance=%.2f required=%.2f",
                user.id, usdc_balance, trade_size,
            )
            return

    # CHECK & REFILL: MATIC gas
    matic_ok = await check_and_refill_matic(user)
    if not matic_ok:
        logger.warning("MATIC refill failed for user=%s, proceeding anyway", user.id)

    # Execute trade via executor
    trade_id = await execute_trade_for_user(
        user=user,
        signal=signal,
        trade_size=trade_size,
        priority=priority,
    )

    if trade_id:
        # Update daily trade counter
        sb.table("users").update(
            {"trades_today": trades_today + 1}
        ).eq("id", user.id).execute()

        logger.info(
            "Trade executed: user=%s trade=%s market=%s action=%s",
            user.id, trade_id, signal.market_slug, signal.action,
        )
