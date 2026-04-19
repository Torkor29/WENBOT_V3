"""/start command handler and main menu."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from shared.supabase_client import get_supabase
from wallet.create import create_wallet
from wallet.encrypt import encrypt

router = Router()
logger = logging.getLogger(__name__)


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\U0001f4b0 Balance", callback_data="cmd_balance"),
                InlineKeyboardButton(text="\U0001f4e5 Deposit", callback_data="cmd_deposit"),
            ],
            [
                InlineKeyboardButton(text="\U0001f4ca Strategies", callback_data="cmd_strategies"),
                InlineKeyboardButton(text="\U0001f4cb Status", callback_data="cmd_status"),
            ],
            [
                InlineKeyboardButton(text="\U0001f4c0 History", callback_data="cmd_history"),
                InlineKeyboardButton(text="\U0001f4e4 Withdraw", callback_data="cmd_withdraw"),
            ],
            [
                InlineKeyboardButton(text="\u2699\ufe0f Settings", callback_data="cmd_settings"),
                InlineKeyboardButton(text="\U0001f511 Export Key", callback_data="cmd_export_key"),
            ],
        ]
    )


BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="\u2b05 Back to menu", callback_data="cmd_menu")]]
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    telegram_id = message.from_user.id
    telegram_username = message.from_user.username or ""
    sb = get_supabase()

    resp = sb.table("users").select("*").eq("telegram_id", telegram_id).execute()

    if resp.data:
        user = resp.data[0]
        wallet_address = user["wallet_address"]
        await message.answer(
            f"Welcome back! Your deposit wallet:\n\n"
            f"<code>{wallet_address}</code>\n\n"
            f"Send <b>USDC.e</b> on <b>Polygon</b> to this address to start copy-trading.",
            reply_markup=main_menu_kb(),
        )
        return

    wallet_address, private_key = create_wallet()
    encrypted_pk = encrypt(private_key)

    sb.table("users").insert(
        {
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
            "wallet_address": wallet_address,
            "encrypted_private_key": encrypted_pk,
        }
    ).execute()

    logger.info("New user created: telegram_id=%s wallet=%s", telegram_id, wallet_address)

    await message.answer(
        f"Welcome to WenBot Copy-Trading!\n\n"
        f"Your personal deposit wallet has been created:\n\n"
        f"<code>{wallet_address}</code>\n\n"
        f"Send <b>USDC.e</b> on <b>Polygon</b> to fund your account.\n"
        f"A small amount of MATIC for gas will be provided automatically.",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "cmd_menu")
async def cb_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "<b>Main Menu</b>\n\nChoose an option:",
        reply_markup=main_menu_kb(),
    )
