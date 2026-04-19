"""/unsubscribe command handler."""

from __future__ import annotations

import logging

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
logger = logging.getLogger(__name__)


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message) -> None:
    telegram_id = message.from_user.id
    sb = get_supabase()

    user_resp = sb.table("users").select("id").eq("telegram_id", telegram_id).execute()
    if not user_resp.data:
        await message.answer("You don't have an account yet. Use /start first.")
        return

    user_id = user_resp.data[0]["id"]

    subs_resp = (
        sb.table("subscriptions")
        .select("id, strategy_id, trade_size, strategies(name)")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .execute()
    )

    subs = subs_resp.data or []
    if not subs:
        await message.answer("You have no active subscriptions.")
        return

    buttons = []
    for sub in subs:
        strategy_name = (
            sub.get("strategies", {}).get("name")
            if isinstance(sub.get("strategies"), dict)
            else sub["strategy_id"][:8]
        )
        buttons.append(
            [InlineKeyboardButton(
                text=f"{strategy_name} (${sub['trade_size']:.2f})",
                callback_data=f"unsub:{sub['id']}",
            )]
        )
    buttons.append([InlineKeyboardButton(text="Cancel", callback_data="unsub:cancel")])

    await message.answer(
        "Select a subscription to deactivate:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("unsub:"))
async def on_unsubscribe(callback: CallbackQuery) -> None:
    value = callback.data.split(":", 1)[1]
    if value == "cancel":
        await callback.answer("Cancelled.")
        await callback.message.edit_text("Unsubscribe cancelled.")
        return

    sub_id = value
    sb = get_supabase()

    sb.table("subscriptions").update({"is_active": False}).eq("id", sub_id).execute()

    logger.info("Subscription deactivated: %s", sub_id)

    await callback.answer("Unsubscribed!")
    await callback.message.edit_text(
        "Subscription deactivated successfully.\n\n"
        "Use /strategies to browse available strategies."
    )
