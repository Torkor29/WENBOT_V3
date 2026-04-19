"""
Trade executor -- executes a complete trade for a given user.

Orchestrates: wallet decryption -> fee tx (BUY only) -> Polymarket order -> Supabase log.
Uses wallet/signer.py for Polymarket communication.
Uses wallet/encrypt.py for decryption.
Uses web3.py (via signer) for USDC.e fee transfers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from shared.config import MIN_TRADE_FEE_RATE, WENBOT_FEE_WALLET
from shared.models import Signal, Subscription, Trade, User
from shared.supabase_client import get_supabase
from wallet.encrypt import decrypt
from wallet.signer import (
    place_buy_order,
    place_sell_order,
    redeem_positions,
    send_usdc_transfer,
)

logger = logging.getLogger(__name__)


async def execute_trade_for_user(
    user: User,
    signal: Signal,
    trade_size: float,
    priority: int,
) -> Optional[str]:
    """Execute a complete trade for a user.

    BUY flow:
    1. Decrypt private key
    2. Calculate fee = trade_size * trade_fee_rate
    3. Send fee USDC.e -> WENBOT_FEE_WALLET (web3.py)
    4. Place BUY order on Polymarket (signer.place_buy_order)
    5. Insert trade into Supabase

    SELL flow:
    1. Decrypt private key
    2. NO FEE on SELL (fee was taken at BUY)
    3. Place SELL order on Polymarket (signer.place_sell_order)
    4. Insert trade into Supabase

    Returns the trade_id or None on failure.
    """
    try:
        # Decrypt private key
        private_key = decrypt(user.encrypted_private_key)
    except Exception:
        logger.exception("Failed to decrypt key for user=%s", user.id)
        return _insert_trade(
            user_id=user.id,
            strategy_id=signal.strategy_id,
            signal=signal,
            fee_info={"fee_rate": 0, "fee_amount": 0, "fee_tx_hash": None},
            order_info={"trade_amount": trade_size},
            priority=priority,
            status="FAILED",
        )

    if signal.action == "BUY":
        return await _execute_buy(user, signal, trade_size, priority, private_key)
    elif signal.action == "SELL":
        return await _execute_sell(user, signal, trade_size, priority, private_key)
    else:
        logger.warning("Unknown action=%s for user=%s", signal.action, user.id)
        return None


async def _execute_buy(
    user: User,
    signal: Signal,
    trade_size: float,
    priority: int,
    private_key: str,
) -> Optional[str]:
    """Execute a BUY trade: fee transfer + Polymarket order."""
    fee_rate = max(user.trade_fee_rate, MIN_TRADE_FEE_RATE)
    fee_amount = trade_size * fee_rate
    trade_amount = trade_size - fee_amount

    if trade_amount <= 0:
        logger.warning("Trade amount non-positive after fee: user=%s", user.id)
        return _insert_trade(
            user_id=user.id,
            strategy_id=signal.strategy_id,
            signal=signal,
            fee_info={"fee_rate": fee_rate, "fee_amount": fee_amount, "fee_tx_hash": None},
            order_info={"trade_amount": trade_amount},
            priority=priority,
            status="SKIPPED",
        )

    # 1. Send fee
    fee_tx_hash = await send_trade_fee(private_key, fee_amount)
    if fee_tx_hash is None:
        logger.warning("Fee transfer failed for user=%s, aborting trade", user.id)
        return _insert_trade(
            user_id=user.id,
            strategy_id=signal.strategy_id,
            signal=signal,
            fee_info={"fee_rate": fee_rate, "fee_amount": fee_amount, "fee_tx_hash": None},
            order_info={"trade_amount": trade_amount},
            priority=priority,
            status="FAILED",
        )

    # 2. Place BUY order
    result = await place_buy_order(
        private_key=private_key,
        token_id=signal.token_id,
        amount_usdc=trade_amount,
        max_price=signal.max_price,
    )

    status = "PLACED" if result["success"] or result["partial"] else "FAILED"

    trade_id = _insert_trade(
        user_id=user.id,
        strategy_id=signal.strategy_id,
        signal=signal,
        fee_info={
            "fee_rate": fee_rate,
            "fee_amount": fee_amount,
            "fee_tx_hash": fee_tx_hash,
        },
        order_info={
            "trade_amount": trade_amount,
            "order_id": result.get("order_id", ""),
            "shares": result.get("shares", 0),
            "cost": result.get("cost", 0),
            "entry_price": result.get("entry_price", 0),
            "status": result.get("status", "FAILED"),
        },
        priority=priority,
        status=status,
    )

    logger.info(
        "BUY executed: user=%s trade=%s market=%s amount=%.2f fee=%.4f status=%s",
        user.id, trade_id, signal.market_slug, trade_amount, fee_amount, status,
    )
    return trade_id


async def _execute_sell(
    user: User,
    signal: Signal,
    trade_size: float,
    priority: int,
    private_key: str,
) -> Optional[str]:
    """Execute a SELL trade: no fee, just Polymarket order."""
    shares_to_sell = signal.shares if signal.shares > 0 else trade_size

    result = await place_sell_order(
        private_key=private_key,
        token_id=signal.token_id,
        shares=shares_to_sell,
    )

    status = "PLACED" if result["success"] or result["partial"] else "FAILED"

    trade_id = _insert_trade(
        user_id=user.id,
        strategy_id=signal.strategy_id,
        signal=signal,
        fee_info={"fee_rate": 0, "fee_amount": 0, "fee_tx_hash": None},
        order_info={
            "trade_amount": 0,
            "order_id": result.get("order_id", ""),
            "sold": result.get("sold", 0),
            "remaining": result.get("remaining", 0),
            "received": result.get("received", 0),
            "status": result.get("status", "FAILED"),
        },
        priority=priority,
        status=status,
    )

    logger.info(
        "SELL executed: user=%s trade=%s market=%s shares=%.4f status=%s received=%.2f$",
        user.id, trade_id, signal.market_slug, shares_to_sell, status,
        result.get("received", 0),
    )
    return trade_id


# ---------------------------------------------------------------------------
# Fee transfer
# ---------------------------------------------------------------------------

async def send_trade_fee(private_key: str, fee_amount: float) -> Optional[str]:
    """Send trade fee in USDC.e to WENBOT_FEE_WALLET.

    Uses web3.py (ERC-20 transfer), NOT py_clob_client.
    Returns tx hash or None on failure.
    """
    if not WENBOT_FEE_WALLET:
        logger.error("WENBOT_FEE_WALLET is not configured")
        return None

    try:
        tx_hash = await asyncio.to_thread(
            send_usdc_transfer,
            private_key,
            WENBOT_FEE_WALLET,
            fee_amount,
        )
        logger.info("Trade fee sent: amount=%.4f tx=%s", fee_amount, tx_hash)
        return tx_hash
    except Exception:
        logger.exception("Trade fee transfer failed: amount=%.4f", fee_amount)
        return None


# ---------------------------------------------------------------------------
# Redeem
# ---------------------------------------------------------------------------

async def try_redeem_for_user(user: User) -> None:
    """Attempt to redeem resolved winning positions for a user."""
    try:
        private_key = decrypt(user.encrypted_private_key)
        results = await redeem_positions(private_key)
        if results:
            logger.info("Redeemed %d positions for user=%s", len(results), user.id)
    except Exception:
        logger.exception("Redeem failed for user=%s", user.id)


# ---------------------------------------------------------------------------
# Supabase trade record
# ---------------------------------------------------------------------------

def _insert_trade(
    user_id: str,
    strategy_id: str,
    signal: Signal,
    fee_info: Dict[str, Any],
    order_info: Dict[str, Any],
    priority: int,
    status: str = "PLACED",
) -> str:
    """Insert a trade record into the trades table in Supabase."""
    sb = get_supabase()

    trade_data = {
        "user_id": user_id,
        "strategy_id": strategy_id,
        "market_slug": signal.market_slug,
        "token_id": signal.token_id,
        "direction": signal.action,
        "side": signal.side,
        "entry_price": order_info.get("entry_price", signal.max_price),
        "amount_usdc": order_info.get("trade_amount") or order_info.get("cost"),
        "shares": order_info.get("shares", 0),
        "trade_fee_rate": fee_info.get("fee_rate"),
        "trade_fee_amount": fee_info.get("fee_amount"),
        "trade_fee_tx_hash": fee_info.get("fee_tx_hash"),
        "order_tx_hash": order_info.get("order_id"),
        "status": status,
        "execution_priority": priority,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    result = sb.table("trades").insert(trade_data).execute()

    trade_id = result.data[0]["id"] if result.data else "unknown"
    logger.info(
        "Trade record inserted: trade_id=%s user=%s strategy=%s status=%s",
        trade_id, user_id, strategy_id, status,
    )
    return trade_id
