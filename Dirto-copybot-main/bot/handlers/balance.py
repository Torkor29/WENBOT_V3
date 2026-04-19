"""/balance command handler."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from shared.supabase_client import get_supabase
from wallet.balance import get_matic_balance, get_usdc_balance
from bot.handlers.start import BACK_KB

router = Router()
logger = logging.getLogger(__name__)


async def _fetch_and_reply(telegram_id: int, answer_func) -> None:
    sb = get_supabase()
    resp = sb.table("users").select("wallet_address").eq("telegram_id", telegram_id).execute()
    if not resp.data:
        await answer_func("You don't have an account yet. Use /start first.")
        return

    wallet = resp.data[0]["wallet_address"]

    loop = asyncio.get_running_loop()
    usdc, matic = await asyncio.gather(
        loop.run_in_executor(None, get_usdc_balance, wallet),
        loop.run_in_executor(None, get_matic_balance, wallet),
    )

    await answer_func(
        f"<b>Wallet Balances</b>\n\n"
        f"<b>USDC.e:</b>  ${usdc:,.2f}\n"
        f"<b>MATIC:</b>   {matic:,.4f}\n\n"
        f"Wallet: <code>{wallet}</code>",
        reply_markup=BACK_KB,
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    await _fetch_and_reply(message.from_user.id, message.answer)


@router.callback_query(F.data == "cmd_balance")
async def cb_balance(callback: CallbackQuery) -> None:
    await callback.answer()
    await _fetch_and_reply(callback.from_user.id, callback.message.answer)
