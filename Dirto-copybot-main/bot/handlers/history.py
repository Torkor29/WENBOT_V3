"""/history command handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from shared.supabase_client import get_supabase
from bot.handlers.start import BACK_KB

router = Router()


async def _show_history(telegram_id: int, answer_func) -> None:
    sb = get_supabase()

    user_resp = sb.table("users").select("id").eq("telegram_id", telegram_id).execute()
    if not user_resp.data:
        await answer_func("You don't have an account yet. Use /start first.")
        return

    user_id = user_resp.data[0]["id"]

    trades_resp = (
        sb.table("trades")
        .select("created_at, market_slug, side, amount_usdc, result, pnl")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    trades = trades_resp.data or []

    if not trades:
        await answer_func("No trade history yet.", reply_markup=BACK_KB)
        return

    lines = ["<b>Last 20 Trades</b>\n"]
    for t in trades:
        dt = (t.get("created_at") or "")[:16].replace("T", " ")
        market = t.get("market_slug") or "?"
        if len(market) > 25:
            market = market[:22] + "..."
        side = t.get("side") or "?"
        amount = t.get("amount_usdc") or 0
        result = t.get("result") or "PENDING"
        pnl = t.get("pnl")
        pnl_str = f"${pnl:+.2f}" if pnl is not None else "-"

        icon = {"WON": "+", "LOST": "-"}.get(result, " ")
        lines.append(
            f"<code>{dt}</code> {icon} {market}\n"
            f"  {side} ${amount:.2f} | {result} | {pnl_str}"
        )

    await answer_func("\n".join(lines), reply_markup=BACK_KB)


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    await _show_history(message.from_user.id, message.answer)


@router.callback_query(F.data == "cmd_history")
async def cb_history(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_history(callback.from_user.id, callback.message.answer)
