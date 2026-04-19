"""Resolver that polls Polymarket for market resolution, updates trades, and triggers redeem."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from shared.models import User
from shared.supabase_client import get_supabase
from engine.executor import try_redeem_for_user

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
POLL_INTERVAL_SECONDS = 30


async def resolver_loop() -> None:
    """Continuously poll for unresolved trades and check market resolution."""
    logger.info("Resolver loop started, polling every %ds", POLL_INTERVAL_SECONDS)
    while True:
        try:
            await _resolve_pending_trades()
        except Exception:
            logger.exception("Error in resolver loop iteration")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _resolve_pending_trades() -> None:
    """Query unresolved trades and check if their markets have resolved."""
    sb = get_supabase()

    result = (
        sb.table("trades")
        .select("*")
        .in_("status", ["PLACED", "FILLED"])
        .is_("resolved_at", "null")
        .execute()
    )

    trades = result.data or []
    if not trades:
        return

    # Group trades by market_slug
    trades_by_market: Dict[str, List[Dict[str, Any]]] = {}
    for trade in trades:
        slug = trade.get("market_slug", "")
        if slug:
            trades_by_market.setdefault(slug, []).append(trade)

    # Collect user_ids that had winning trades (for redeem)
    users_to_redeem: set[str] = set()

    async with aiohttp.ClientSession() as session:
        for market_slug, market_trades in trades_by_market.items():
            resolution = await _check_market_resolution(session, market_slug)
            if resolution is None:
                continue

            for trade in market_trades:
                won = await _process_resolved_trade(trade, resolution)
                if won:
                    users_to_redeem.add(trade["user_id"])

    # Trigger redeem for users with winning trades
    if users_to_redeem:
        await _redeem_for_users(users_to_redeem)


async def _check_market_resolution(
    session: aiohttp.ClientSession,
    market_slug: str,
) -> Optional[Dict[str, Any]]:
    """Query the Gamma API to check if a market has resolved."""
    url = f"{GAMMA_API_BASE}/markets?slug={market_slug}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                logger.warning(
                    "Gamma API error: status=%d market=%s", resp.status, market_slug
                )
                return None

            data = await resp.json()
            if not data:
                return None

            market = data[0] if isinstance(data, list) else data

            if not market.get("resolved", False):
                return None

            outcome = market.get("outcome", "")
            resolution_price = market.get("outcomePrices")

            logger.info("Market resolved: slug=%s outcome=%s", market_slug, outcome)

            return {
                "resolved": True,
                "outcome": outcome,
                "resolution_price": resolution_price,
            }

    except asyncio.TimeoutError:
        logger.warning("Gamma API timeout for market=%s", market_slug)
        return None
    except Exception:
        logger.exception("Error checking market resolution: market=%s", market_slug)
        return None


async def _process_resolved_trade(
    trade: Dict[str, Any],
    resolution: Dict[str, Any],
) -> bool:
    """Update a trade record based on market resolution. Returns True if WON."""
    sb = get_supabase()

    trade_id = trade["id"]
    trade_side = trade.get("side", "")
    trade_direction = trade.get("direction", "")
    shares = trade.get("shares", 0) or 0
    cost = trade.get("amount_usdc", 0) or 0
    outcome = resolution.get("outcome", "")

    # Determine win/loss
    trade_won = (
        (trade_side == "YES" and outcome.lower() == "yes")
        or (trade_side == "NO" and outcome.lower() == "no")
    )

    result = "WON" if trade_won else "LOST"

    # PnL based on shares: won = (shares * 1.0) - cost, lost = 0 - cost
    if trade_direction == "BUY":
        win_value = shares * 1.0 if trade_won else 0.0
        pnl = win_value - cost
    elif trade_direction == "SELL":
        # For SELL trades, received USDC is already logged
        received = trade.get("received", 0) or 0
        pnl = received  # SELL PnL is just what was received
    else:
        pnl = cost if trade_won else -cost

    now_iso = datetime.now(timezone.utc).isoformat()

    sb.table("trades").update(
        {
            "result": result,
            "pnl": round(pnl, 4),
            "resolved_at": now_iso,
            "status": "FILLED",
        }
    ).eq("id", trade_id).execute()

    logger.info(
        "Trade resolved: trade=%s result=%s pnl=%.2f market=%s",
        trade_id, result, pnl, trade.get("market_slug", ""),
    )

    # Update strategy stats
    strategy_id = trade.get("strategy_id")
    if strategy_id:
        await _update_strategy_stats(strategy_id)

    # Notify user
    user_id = trade.get("user_id", "unknown")
    logger.info(
        "NOTIFICATION: user=%s trade=%s result=%s pnl=%.2f on market=%s",
        user_id, trade_id, result, pnl, trade.get("market_slug", ""),
    )

    return trade_won


async def _redeem_for_users(user_ids: set[str]) -> None:
    """Trigger redeem for users with winning resolved trades."""
    sb = get_supabase()

    for user_id in user_ids:
        try:
            user_result = sb.table("users").select("*").eq("id", user_id).execute()
            if not user_result.data:
                continue

            row = user_result.data[0]
            user = User(
                id=row["id"],
                created_at=datetime.fromisoformat(
                    row.get("created_at", "2024-01-01T00:00:00+00:00").replace("Z", "+00:00")
                ),
                telegram_id=row.get("telegram_id", 0),
                telegram_username=row.get("telegram_username"),
                wallet_address=row["wallet_address"],
                encrypted_private_key=row["encrypted_private_key"],
            )

            await try_redeem_for_user(user)

        except Exception:
            logger.exception("Redeem failed for user=%s", user_id)


async def _update_strategy_stats(strategy_id: str) -> None:
    """Recalculate and update strategy aggregate stats."""
    sb = get_supabase()

    result = (
        sb.table("trades")
        .select("result, pnl")
        .eq("strategy_id", strategy_id)
        .not_.is_("resolved_at", "null")
        .execute()
    )

    resolved_trades = result.data or []
    if not resolved_trades:
        return

    total_trades = len(resolved_trades)
    total_pnl = sum(t.get("pnl", 0) or 0 for t in resolved_trades)
    wins = sum(1 for t in resolved_trades if t.get("result") == "WON")
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0.0

    sb.table("strategies").update(
        {
            "total_trades": total_trades,
            "total_pnl": round(total_pnl, 4),
            "win_rate": round(win_rate, 2),
        }
    ).eq("id", strategy_id).execute()

    logger.info(
        "Strategy stats updated: strategy=%s trades=%d pnl=%.2f win_rate=%.1f%%",
        strategy_id, total_trades, total_pnl, win_rate,
    )
