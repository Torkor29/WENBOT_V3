"""Notification helpers – send formatted messages to users via Bot instance."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from aiogram import Bot

logger = logging.getLogger(__name__)


async def notify_trade_placed(
    bot: Bot,
    user: Dict[str, Any],
    signal: Dict[str, Any],
    trade_amount: float,
    entry_price: float,
) -> None:
    """Notify the user that a trade has been placed."""
    telegram_id = user["telegram_id"]
    market = signal.get("market_slug", "?")
    side = signal.get("side", "?")

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"<b>Trade Placed</b>\n\n"
                f"Market: {market}\n"
                f"Side: {side}\n"
                f"Amount: ${trade_amount:.2f}\n"
                f"Entry price: {entry_price:.4f}"
            ),
        )
    except Exception:
        logger.exception("Failed to notify trade placed to %s", telegram_id)


async def notify_trade_result(
    bot: Bot,
    user: Dict[str, Any],
    trade: Dict[str, Any],
) -> None:
    """Notify the user of a trade result (WON / LOST)."""
    telegram_id = user["telegram_id"]
    result = trade.get("result", "UNKNOWN")
    pnl = trade.get("pnl", 0.0)
    market = trade.get("market_slug", "?")
    side = trade.get("side", "?")
    amount = trade.get("amount_usdc", 0.0)

    icon = "+" if result == "WON" else "-" if result == "LOST" else " "
    pnl_str = f"${pnl:+.2f}" if pnl is not None else "-"

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"<b>Trade Result: {result}</b> {icon}\n\n"
                f"Market: {market}\n"
                f"Side: {side}\n"
                f"Amount: ${amount:.2f}\n"
                f"PnL: {pnl_str}"
            ),
        )
    except Exception:
        logger.exception("Failed to notify trade result to %s", telegram_id)


async def notify_daily_recap(
    bot: Bot,
    user: Dict[str, Any],
    trades_count: int,
    wins: int,
    total_pnl: float,
    perf_fee: float,
) -> None:
    """Send a daily performance recap to the user."""
    telegram_id = user["telegram_id"]
    losses = trades_count - wins
    win_rate = (wins / trades_count * 100) if trades_count > 0 else 0.0

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"<b>Daily Recap</b>\n\n"
                f"Trades: {trades_count} ({wins}W / {losses}L)\n"
                f"Win rate: {win_rate:.1f}%\n"
                f"PnL: ${total_pnl:+.2f}\n"
                f"Performance fee: ${perf_fee:.2f}"
            ),
        )
    except Exception:
        logger.exception("Failed to send daily recap to %s", telegram_id)


async def notify_low_balance(
    bot: Bot,
    user: Dict[str, Any],
    balance: float,
) -> None:
    """Warn the user their USDC.e balance is running low."""
    telegram_id = user["telegram_id"]

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"<b>Low Balance Warning</b>\n\n"
                f"Your USDC.e balance is <b>${balance:.2f}</b>.\n"
                f"Trades may be skipped if your balance is insufficient.\n\n"
                f"Use /deposit to top up."
            ),
        )
    except Exception:
        logger.exception("Failed to send low balance alert to %s", telegram_id)


async def notify_error(
    bot: Bot,
    user: Dict[str, Any],
    message: str,
) -> None:
    """Send an error notification to the user."""
    telegram_id = user["telegram_id"]

    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=f"<b>Error</b>\n\n{message}",
        )
    except Exception:
        logger.exception("Failed to send error notification to %s", telegram_id)
