"""Daily performance fee job running at midnight UTC."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from shared.config import PERF_FEE_RATE, WENBOT_FEE_WALLET
from shared.supabase_client import get_supabase
from wallet.balance import get_usdc_balance
from wallet.encrypt import decrypt
from wallet.signer import send_usdc_transfer

logger = logging.getLogger(__name__)


async def daily_perf_fee_job() -> None:
    """Run the daily performance fee collection at midnight UTC, forever."""
    logger.info("Performance fee cron started")
    while True:
        await _sleep_until_midnight_utc()
        try:
            await _collect_performance_fees()
        except Exception:
            logger.exception("Error in daily performance fee job")


async def _sleep_until_midnight_utc() -> None:
    """Sleep until the next midnight UTC."""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    delta = (tomorrow - now).total_seconds()
    logger.info("Performance fee cron sleeping %.0f seconds until midnight UTC", delta)
    await asyncio.sleep(delta)


async def _collect_performance_fees() -> None:
    """Collect performance fees from all active users based on yesterday's PnL."""
    sb = get_supabase()
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()

    # Get all active users
    users_result = (
        sb.table("users")
        .select("*")
        .eq("is_active", True)
        .execute()
    )

    users = users_result.data or []
    if not users:
        logger.info("No active users for performance fee collection")
        return

    logger.info(
        "Collecting performance fees for %d users, date=%s", len(users), yesterday_str
    )

    for user_row in users:
        try:
            await _process_user_perf_fee(user_row, yesterday, yesterday_str)
        except Exception:
            logger.exception(
                "Error processing performance fee for user=%s", user_row.get("id")
            )


async def _process_user_perf_fee(
    user_row: Dict[str, Any],
    fee_date: date,
    fee_date_str: str,
) -> None:
    """Process performance fee for a single user."""
    sb = get_supabase()
    user_id = user_row["id"]

    # Get resolved trades from yesterday
    start_of_day = datetime(
        fee_date.year, fee_date.month, fee_date.day, tzinfo=timezone.utc
    ).isoformat()
    end_of_day = datetime(
        fee_date.year, fee_date.month, fee_date.day, 23, 59, 59, tzinfo=timezone.utc
    ).isoformat()

    trades_result = (
        sb.table("trades")
        .select("pnl, result")
        .eq("user_id", user_id)
        .not_.is_("resolved_at", "null")
        .gte("resolved_at", start_of_day)
        .lte("resolved_at", end_of_day)
        .execute()
    )

    trades = trades_result.data or []

    if not trades:
        logger.debug("No resolved trades yesterday for user=%s", user_id)
        return

    total_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
    total_trades_count = len(trades)
    wins = sum(1 for t in trades if t.get("result") == "WON")
    losses = total_trades_count - wins

    now_iso = datetime.now(timezone.utc).isoformat()

    # If PnL <= 0, skip fee collection
    if total_pnl <= 0:
        sb.table("daily_performance_fees").insert(
            {
                "user_id": user_id,
                "date": fee_date_str,
                "total_trades": total_trades_count,
                "wins": wins,
                "losses": losses,
                "total_pnl": round(total_pnl, 4),
                "perf_fee_rate": PERF_FEE_RATE,
                "perf_fee_amount": 0,
                "status": "SKIPPED",
                "created_at": now_iso,
            }
        ).execute()

        logger.info(
            "Perf fee SKIPPED: user=%s pnl=%.2f (non-positive)", user_id, total_pnl
        )
        return

    # Calculate performance fee
    perf_fee = total_pnl * PERF_FEE_RATE

    # Check user balance and adjust if needed
    wallet_address = user_row["wallet_address"]
    usdc_balance = get_usdc_balance(wallet_address)

    if perf_fee > usdc_balance:
        logger.info(
            "Adjusting perf fee: user=%s fee=%.4f > balance=%.4f",
            user_id,
            perf_fee,
            usdc_balance,
        )
        perf_fee = usdc_balance

    # Skip if fee is too small
    if perf_fee < 0.01:
        sb.table("daily_performance_fees").insert(
            {
                "user_id": user_id,
                "date": fee_date_str,
                "total_trades": total_trades_count,
                "wins": wins,
                "losses": losses,
                "total_pnl": round(total_pnl, 4),
                "perf_fee_rate": PERF_FEE_RATE,
                "perf_fee_amount": round(perf_fee, 4),
                "status": "SKIPPED",
                "created_at": now_iso,
            }
        ).execute()

        logger.info(
            "Perf fee SKIPPED: user=%s fee=%.4f too small", user_id, perf_fee
        )
        return

    # Send fee transfer
    try:
        private_key = decrypt(user_row["encrypted_private_key"])
        tx_hash = send_usdc_transfer(
            private_key=private_key,
            to_address=WENBOT_FEE_WALLET,
            amount_usdc=perf_fee,
        )

        sb.table("daily_performance_fees").insert(
            {
                "user_id": user_id,
                "date": fee_date_str,
                "total_trades": total_trades_count,
                "wins": wins,
                "losses": losses,
                "total_pnl": round(total_pnl, 4),
                "perf_fee_rate": PERF_FEE_RATE,
                "perf_fee_amount": round(perf_fee, 4),
                "perf_fee_tx_hash": tx_hash,
                "status": "SENT",
                "created_at": now_iso,
            }
        ).execute()

        logger.info(
            "Perf fee SENT: user=%s pnl=%.2f fee=%.4f tx=%s",
            user_id,
            total_pnl,
            perf_fee,
            tx_hash,
        )

        # Notify user with daily recap
        logger.info(
            "NOTIFICATION: user=%s daily recap - trades=%d wins=%d pnl=%.2f fee=%.4f",
            user_id,
            total_trades_count,
            wins,
            total_pnl,
            perf_fee,
        )

    except Exception:
        logger.exception("Performance fee transfer failed: user=%s", user_id)

        sb.table("daily_performance_fees").insert(
            {
                "user_id": user_id,
                "date": fee_date_str,
                "total_trades": total_trades_count,
                "wins": wins,
                "losses": losses,
                "total_pnl": round(total_pnl, 4),
                "perf_fee_rate": PERF_FEE_RATE,
                "perf_fee_amount": round(perf_fee, 4),
                "status": "FAILED",
                "created_at": now_iso,
            }
        ).execute()
