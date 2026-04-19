"""/strategies command handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from shared.supabase_client import get_supabase

router = Router()


def _build_strategies_text_and_kb(strategies: list) -> tuple[str, InlineKeyboardMarkup]:
    if not strategies:
        return "No active public strategies available at the moment.", InlineKeyboardMarkup(inline_keyboard=[])

    lines = ["<b>Available Strategies</b>\n"]
    buttons = []
    for s in strategies:
        win_pct = (s.get("win_rate") or 0) * 100
        total = s.get("total_trades") or 0
        desc = s.get("description") or "No description"
        lines.append(
            f"<b>{s['name']}</b>\n"
            f"  {desc}\n"
            f"  Win rate: {win_pct:.1f}% | Trades: {total}\n"
        )
        buttons.append(
            [InlineKeyboardButton(
                text=f"Subscribe to {s['name']}",
                callback_data=f"sub_pick:{s['id']}",
            )]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    return "\n".join(lines), kb


async def _show_strategies(answer_func) -> None:
    sb = get_supabase()
    resp = (
        sb.table("strategies")
        .select("*")
        .eq("status", "active")
        .eq("visibility", "public")
        .execute()
    )
    text, kb = _build_strategies_text_and_kb(resp.data or [])
    await answer_func(text, reply_markup=kb)


@router.message(Command("strategies"))
async def cmd_strategies(message: Message) -> None:
    await _show_strategies(message.answer)


@router.callback_query(F.data == "cmd_strategies")
async def cb_strategies(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_strategies(callback.message.answer)
