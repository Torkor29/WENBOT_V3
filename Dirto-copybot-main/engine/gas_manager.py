"""MATIC gas refill manager with anti-exploit protections."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from shared.config import (
    MATIC_MAX_REFILLS,
    MATIC_MAX_TOTAL,
    MATIC_MIN_BALANCE,
    MATIC_REFILL_AMOUNT,
    MATIC_REFILL_COOLDOWN_SECONDS,
    MIN_USDC_FOR_MATIC_REFILL,
    WENBOT_PRIVATE_KEY,
)
from shared.models import User
from shared.supabase_client import get_supabase
from wallet.balance import get_matic_balance, get_usdc_balance
from wallet.signer import send_matic_transfer

logger = logging.getLogger(__name__)


async def check_and_refill_matic(user: User) -> bool:
    """Check MATIC balance and refill if needed, with 5 anti-exploit checks.

    Returns True if refill was sent or balance was already sufficient.
    Returns False if refill was blocked by a protection check.
    """
    wallet = user.wallet_address

    # Check current MATIC balance
    matic_balance = get_matic_balance(wallet)
    if matic_balance >= MATIC_MIN_BALANCE:
        logger.debug(
            "MATIC balance OK for user=%s balance=%.4f", user.id, matic_balance
        )
        return True

    logger.info(
        "MATIC balance low for user=%s balance=%.6f, evaluating refill",
        user.id,
        matic_balance,
    )

    # CHECK 1: Lifetime cap on refills
    if user.matic_refills_count >= MATIC_MAX_REFILLS:
        await alert_admin(
            f"User {user.id} hit MATIC refill lifetime cap "
            f"({user.matic_refills_count}/{MATIC_MAX_REFILLS})",
            user,
        )
        logger.warning(
            "MATIC refill blocked: lifetime cap reached user=%s count=%d",
            user.id,
            user.matic_refills_count,
        )
        return False

    if user.matic_total_sent >= MATIC_MAX_TOTAL:
        await alert_admin(
            f"User {user.id} hit MATIC total sent cap "
            f"({user.matic_total_sent:.4f}/{MATIC_MAX_TOTAL})",
            user,
        )
        logger.warning(
            "MATIC refill blocked: total sent cap reached user=%s total=%.4f",
            user.id,
            user.matic_total_sent,
        )
        return False

    # CHECK 2: Minimum USDC.e balance to warrant a refill
    usdc_balance = get_usdc_balance(wallet)
    if usdc_balance < MIN_USDC_FOR_MATIC_REFILL:
        logger.info(
            "MATIC refill skipped: USDC balance too low user=%s usdc=%.2f",
            user.id,
            usdc_balance,
        )
        return False

    # CHECK 3: Rate limit - 1 refill per 24 hours
    if user.last_matic_refill_at is not None:
        if isinstance(user.last_matic_refill_at, datetime):
            last_refill_ts = user.last_matic_refill_at.timestamp()
        else:
            last_refill_ts = float(user.last_matic_refill_at)
        elapsed = time.time() - last_refill_ts
        if elapsed < MATIC_REFILL_COOLDOWN_SECONDS:
            remaining_h = (MATIC_REFILL_COOLDOWN_SECONDS - elapsed) / 3600
            logger.info(
                "MATIC refill rate-limited: user=%s cooldown remaining=%.1fh",
                user.id,
                remaining_h,
            )
            return False

    # CHECK 4: Verify previous MATIC was consumed as gas, not drained
    # If the balance is low (below threshold) it implies gas consumption.
    # If the user still has significant MATIC, something is wrong.
    if matic_balance > MATIC_MIN_BALANCE * 0.5 and user.matic_refills_count > 0:
        # Balance is not critically low but below threshold - suspicious if
        # we already refilled before.  This is a soft check; proceed with
        # a warning so the admin can review.
        await alert_admin(
            f"User {user.id} MATIC balance {matic_balance:.6f} is borderline "
            f"after {user.matic_refills_count} refill(s). Possible drain.",
            user,
        )

    # CHECK 5: Ensure refill amount won't exceed lifetime total cap
    projected_total = user.matic_total_sent + MATIC_REFILL_AMOUNT
    if projected_total > MATIC_MAX_TOTAL:
        await alert_admin(
            f"User {user.id} refill would exceed lifetime cap "
            f"(projected {projected_total:.4f} > {MATIC_MAX_TOTAL})",
            user,
        )
        logger.warning(
            "MATIC refill blocked: would exceed lifetime total user=%s", user.id
        )
        return False

    # All checks passed - send MATIC refill
    try:
        tx_hash = send_matic_transfer(
            private_key=WENBOT_PRIVATE_KEY,
            to_address=wallet,
            amount_matic=MATIC_REFILL_AMOUNT,
        )
        logger.info(
            "MATIC refill sent: user=%s amount=%.4f tx=%s",
            user.id,
            MATIC_REFILL_AMOUNT,
            tx_hash,
        )
    except Exception:
        logger.exception("MATIC refill transaction failed for user=%s", user.id)
        return False

    # Update user counters in Supabase
    now_iso = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    sb.table("users").update(
        {
            "matic_refills_count": user.matic_refills_count + 1,
            "matic_total_sent": user.matic_total_sent + MATIC_REFILL_AMOUNT,
            "last_matic_refill_at": now_iso,
        }
    ).eq("id", user.id).execute()

    return True


async def flag_user(user: User, reason: str) -> None:
    """Flag a user with a critical admin alert."""
    logger.critical("USER FLAGGED: user=%s reason=%s", user.id, reason)
    sb = get_supabase()
    sb.table("admin_alerts").insert(
        {
            "user_id": user.id,
            "severity": "critical",
            "message": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


async def alert_admin(message: str, user: User) -> None:
    """Insert a warning-level admin alert."""
    logger.warning("ADMIN ALERT: user=%s message=%s", user.id, message)
    sb = get_supabase()
    sb.table("admin_alerts").insert(
        {
            "user_id": user.id,
            "severity": "warning",
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()
