"""/withdraw flow – multi-step FSM for USDC.e withdrawal."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from web3 import Web3

from shared.supabase_client import get_supabase
from wallet.balance import get_usdc_balance
from wallet.encrypt import decrypt
from wallet.signer import send_usdc_transfer

router = Router()
logger = logging.getLogger(__name__)


class WithdrawFlow(StatesGroup):
    entering_address = State()
    entering_amount = State()
    confirming = State()


async def _start_withdraw(telegram_id: int, answer_func, state: FSMContext) -> None:
    sb = get_supabase()

    user_resp = (
        sb.table("users")
        .select("id, wallet_address, encrypted_private_key")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    if not user_resp.data:
        await answer_func("You don't have an account yet. Use /start first.")
        return

    user = user_resp.data[0]
    await state.update_data(
        user_id=user["id"],
        wallet=user["wallet_address"],
        enc_pk=user["encrypted_private_key"],
    )
    await state.set_state(WithdrawFlow.entering_address)
    await answer_func("Enter the <b>destination address</b> (Polygon network):")


@router.message(Command("withdraw"))
async def cmd_withdraw(message: Message, state: FSMContext) -> None:
    await _start_withdraw(message.from_user.id, message.answer, state)


@router.callback_query(F.data == "cmd_withdraw")
async def cb_withdraw(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _start_withdraw(callback.from_user.id, callback.message.answer, state)


# ── Step 1: destination address ───────────────────────────────────────

@router.message(WithdrawFlow.entering_address)
async def on_address(message: Message, state: FSMContext) -> None:
    raw_addr = (message.text or "").strip()

    try:
        dest = Web3.to_checksum_address(raw_addr)
    except (ValueError, Exception):
        await message.answer(
            "Invalid Polygon address. Please enter a valid address:"
        )
        return

    await state.update_data(destination=dest)
    await state.set_state(WithdrawFlow.entering_amount)

    data = await state.get_data()
    loop = asyncio.get_running_loop()
    usdc = await loop.run_in_executor(None, get_usdc_balance, data["wallet"])
    await state.update_data(available_usdc=usdc)

    await message.answer(
        f"Available: <b>${usdc:,.2f}</b> USDC.e\n\n"
        f"Enter amount to withdraw (or <code>max</code>):"
    )


# ── Step 2: amount ────────────────────────────────────────────────────

_CONFIRM_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Confirm", callback_data="wd_confirm"),
            InlineKeyboardButton(text="Cancel", callback_data="wd_cancel"),
        ]
    ]
)


@router.message(WithdrawFlow.entering_amount)
async def on_amount(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    available = data.get("available_usdc", 0.0)
    text = (message.text or "").strip().lower()

    if text == "max":
        amount = available
    else:
        try:
            amount = float(text.replace("$", ""))
            if amount <= 0:
                raise ValueError
        except (ValueError, AttributeError):
            await message.answer("Please enter a valid amount or <code>max</code>.")
            return

    if amount > available:
        await message.answer(
            f"Insufficient balance. You have ${available:,.2f} USDC.e."
        )
        return

    if amount < 0.01:
        await message.answer("Minimum withdrawal is $0.01.")
        return

    await state.update_data(amount=amount)
    await state.set_state(WithdrawFlow.confirming)
    await message.answer(
        f"<b>Withdrawal Summary</b>\n\n"
        f"To: <code>{data['destination']}</code>\n"
        f"Amount: <b>${amount:,.2f}</b> USDC.e\n"
        f"Network: Polygon\n\n"
        f"Confirm?",
        reply_markup=_CONFIRM_KB,
    )


# ── Step 3: confirm and send ─────────────────────────────────────────

@router.callback_query(F.data == "wd_confirm", WithdrawFlow.confirming)
async def on_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback.answer()
    await callback.message.edit_text("Processing withdrawal ...")

    try:
        private_key = decrypt(data["enc_pk"])
        loop = asyncio.get_running_loop()
        tx_hash = await loop.run_in_executor(
            None,
            send_usdc_transfer,
            private_key,
            data["destination"],
            data["amount"],
        )
    except Exception:
        logger.exception("Withdrawal failed for user %s", data.get("user_id"))
        await callback.message.edit_text(
            "Withdrawal failed. Please try again later or contact support."
        )
        await state.clear()
        return
    finally:
        # Ensure private_key is not retained
        private_key = ""  # noqa: F841

    logger.info(
        "Withdrawal sent: user=%s amount=%s to=%s tx=%s",
        data.get("user_id"),
        data["amount"],
        data["destination"],
        tx_hash,
    )

    await callback.message.edit_text(
        f"Withdrawal sent!\n\n"
        f"Amount: <b>${data['amount']:,.2f}</b> USDC.e\n"
        f"To: <code>{data['destination']}</code>\n"
        f"Tx: <a href='https://polygonscan.com/tx/{tx_hash}'>{tx_hash[:16]}...</a>"
    )
    await state.clear()


@router.callback_query(F.data == "wd_cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Cancelled.")
    await callback.message.edit_text("Withdrawal cancelled.")
