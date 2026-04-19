"""/deposit command handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from shared.supabase_client import get_supabase
from bot.handlers.start import BACK_KB

router = Router()


async def _show_deposit(telegram_id: int, answer_func) -> None:
    sb = get_supabase()
    resp = sb.table("users").select("wallet_address").eq("telegram_id", telegram_id).execute()
    if not resp.data:
        await answer_func("You don't have an account yet. Use /start first.")
        return

    wallet_address = resp.data[0]["wallet_address"]
    await answer_func(
        f"<b>Deposit USDC.e on Polygon</b>\n\n"
        f"Send USDC.e to your personal wallet:\n\n"
        f"<code>{wallet_address}</code>\n\n"
        f"<b>Network:</b> Polygon (MATIC)\n"
        f"<b>Token:</b> USDC.e (Bridged USDC)\n\n"
        f"Gas (MATIC/POL) is auto-refilled when you have sufficient USDC.e balance. "
        f"No need to send MATIC manually.",
        reply_markup=BACK_KB,
    )


@router.message(Command("deposit"))
async def cmd_deposit(message: Message) -> None:
    await _show_deposit(message.from_user.id, message.answer)


@router.callback_query(F.data == "cmd_deposit")
async def cb_deposit(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_deposit(callback.from_user.id, callback.message.answer)
