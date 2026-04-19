"""/status command handler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from shared.supabase_client import get_supabase
from wallet.balance import get_usdc_balance
from bot.handlers.start import BACK_KB

router = Router()


async def _show_status(telegram_id: int, answer_func) -> None:
    sb = get_supabase()

    user_resp = (
        sb.table("users")
        .select("id, wallet_address, trade_fee_rate, is_paused")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    if not user_resp.data:
        await answer_func("You don't have an account yet. Use /start first.")
        return

    user = user_resp.data[0]
    user_id = user["id"]
    wallet = user["wallet_address"]

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    trades_resp = (
        sb.table("trades")
        .select("created_at, result, pnl")
        .eq("user_id", user_id)
        .gte("created_at", month_start)
        .execute()
    )
    trades = trades_resp.data or []

    pnl_day = 0.0
    pnl_week = 0.0
    pnl_month = 0.0
    wins_today = 0
    losses_today = 0
    trades_today_count = 0

    for t in trades:
        pnl_val = t.get("pnl") or 0.0
        created = t.get("created_at", "")
        pnl_month += pnl_val
        if created >= week_start:
            pnl_week += pnl_val
        if created >= today_start:
            pnl_day += pnl_val
            trades_today_count += 1
            if t.get("result") == "WON":
                wins_today += 1
            elif t.get("result") == "LOST":
                losses_today += 1

    subs_resp = (
        sb.table("subscriptions")
        .select("id")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .execute()
    )
    active_subs = len(subs_resp.data or [])

    loop = asyncio.get_running_loop()
    usdc = await loop.run_in_executor(None, get_usdc_balance, wallet)

    fee_pct = (user.get("trade_fee_rate") or 0.01) * 100
    paused_label = "PAUSED" if user.get("is_paused") else "ACTIVE"

    def _fmt_pnl(val: float) -> str:
        sign = "+" if val >= 0 else ""
        return f"{sign}${val:.2f}"

    await answer_func(
        f"<b>Account Status</b>  [{paused_label}]\n\n"
        f"<b>USDC.e Balance:</b> ${usdc:,.2f}\n\n"
        f"<b>PnL Today:</b> {_fmt_pnl(pnl_day)}\n"
        f"<b>PnL This Week:</b> {_fmt_pnl(pnl_week)}\n"
        f"<b>PnL This Month:</b> {_fmt_pnl(pnl_month)}\n\n"
        f"<b>Active Strategies:</b> {active_subs}\n"
        f"<b>Trades Today:</b> {trades_today_count} "
        f"({wins_today}W / {losses_today}L)\n"
        f"<b>Fee Rate:</b> {fee_pct:.1f}%",
        reply_markup=BACK_KB,
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    await _show_status(message.from_user.id, message.answer)


@router.callback_query(F.data == "cmd_status")
async def cb_status(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_status(callback.from_user.id, callback.message.answer)
