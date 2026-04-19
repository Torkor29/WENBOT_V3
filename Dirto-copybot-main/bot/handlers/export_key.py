"""/export_key command handler – exports the user's private key with safeguards."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from shared.supabase_client import get_supabase
from wallet.encrypt import decrypt

router = Router()
logger = logging.getLogger(__name__)

_CONFIRM_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes, export my key", callback_data="expkey_yes"),
            InlineKeyboardButton(text="No, cancel", callback_data="expkey_no"),
        ]
    ]
)


async def _show_export_warning(answer_func) -> None:
    await answer_func(
        "<b>WARNING</b>\n\n"
        "Your private key gives <b>full control</b> over your wallet funds.\n"
        "Never share it with anyone.\n\n"
        "The key will be displayed for 30 seconds, then the message will be deleted.\n\n"
        "Do you want to continue?",
        reply_markup=_CONFIRM_KB,
    )


@router.message(Command("export_key"))
async def cmd_export_key(message: Message) -> None:
    await _show_export_warning(message.answer)


@router.callback_query(F.data == "cmd_export_key")
async def cb_export_key(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_export_warning(callback.message.answer)


@router.callback_query(F.data == "expkey_no")
async def on_cancel(callback: CallbackQuery) -> None:
    await callback.answer("Cancelled.")
    await callback.message.edit_text("Export cancelled.")


@router.callback_query(F.data == "expkey_yes")
async def on_confirm(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    sb = get_supabase()

    user_resp = (
        sb.table("users")
        .select("id, encrypted_private_key")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    if not user_resp.data:
        await callback.answer("Account not found.", show_alert=True)
        return

    user = user_resp.data[0]
    user_id = user["id"]

    # Rate limit: 1 export per 24h
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    alerts_resp = (
        sb.table("admin_alerts")
        .select("id")
        .eq("user_id", user_id)
        .eq("alert_type", "key_export")
        .gte("created_at", cutoff)
        .execute()
    )
    if alerts_resp.data:
        await callback.answer(
            "You can only export your key once every 24 hours.",
            show_alert=True,
        )
        return

    await callback.answer()
    await callback.message.edit_text("Decrypting ...")

    try:
        private_key = decrypt(user["encrypted_private_key"])
    except Exception:
        logger.exception("Failed to decrypt key for user %s", user_id)
        await callback.message.edit_text("Decryption error. Contact support.")
        return

    # Send key in a separate message that will be deleted
    key_msg = await callback.message.answer(
        f"<b>Your Private Key (auto-deletes in 30s):</b>\n\n"
        f"<tg-spoiler>{private_key}</tg-spoiler>",
    )

    # Clear from local scope immediately after sending
    private_key = ""  # noqa: F841

    await callback.message.edit_text("Key exported. The message will self-destruct in 30 seconds.")

    # Log the export
    sb.table("admin_alerts").insert(
        {
            "user_id": user_id,
            "alert_type": "key_export",
            "message": f"Private key exported by user {telegram_id}",
        }
    ).execute()

    logger.info("Key exported for user %s (telegram_id=%s)", user_id, telegram_id)

    # Wait and delete
    await asyncio.sleep(30)
    try:
        await key_msg.delete()
    except Exception:
        logger.warning("Could not delete key message for user %s", user_id)
