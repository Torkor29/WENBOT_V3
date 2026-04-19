"""/settings command handler."""

from __future__ import annotations

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

from shared.supabase_client import get_supabase

router = Router()
logger = logging.getLogger(__name__)


class SettingsEdit(StatesGroup):
    waiting_trade_size = State()
    waiting_fee_rate = State()
    waiting_max_trades = State()


def _settings_kb(is_paused: bool) -> InlineKeyboardMarkup:
    pause_label = "Resume" if is_paused else "Pause"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Trade Size", callback_data="set_edit:trade_size"),
                InlineKeyboardButton(text="Fee Rate", callback_data="set_edit:fee_rate"),
            ],
            [
                InlineKeyboardButton(text="Max Trades/Day", callback_data="set_edit:max_trades"),
                InlineKeyboardButton(text=pause_label, callback_data="set_toggle_pause"),
            ],
        ]
    )


def _format_settings(user: dict) -> str:
    fee_pct = (user.get("trade_fee_rate") or 0.01) * 100
    paused = "PAUSED" if user.get("is_paused") else "ACTIVE"
    return (
        f"<b>Settings</b>  [{paused}]\n\n"
        f"<b>Trade Size:</b> ${user.get('max_trade_size', 4.0):.2f}\n"
        f"<b>Fee Rate:</b> {fee_pct:.1f}%\n"
        f"<b>Max Trades/Day:</b> {user.get('max_trades_per_day', 50)}\n"
    )


def _get_user(telegram_id: int) -> dict | None:
    sb = get_supabase()
    resp = (
        sb.table("users")
        .select("id, max_trade_size, trade_fee_rate, max_trades_per_day, is_paused")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    user = _get_user(message.from_user.id)
    if not user:
        await message.answer("You don't have an account yet. Use /start first.")
        return
    await message.answer(
        _format_settings(user),
        reply_markup=_settings_kb(user.get("is_paused", False)),
    )


@router.callback_query(F.data == "cmd_settings")
async def cb_settings(callback: CallbackQuery) -> None:
    user = _get_user(callback.from_user.id)
    if not user:
        await callback.answer("Account not found.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        _format_settings(user),
        reply_markup=_settings_kb(user.get("is_paused", False)),
    )


# ── Toggle pause ──────────────────────────────────────────────────────

@router.callback_query(F.data == "set_toggle_pause")
async def on_toggle_pause(callback: CallbackQuery) -> None:
    user = _get_user(callback.from_user.id)
    if not user:
        await callback.answer("Account not found.", show_alert=True)
        return

    new_val = not user.get("is_paused", False)
    sb = get_supabase()
    sb.table("users").update({"is_paused": new_val}).eq("id", user["id"]).execute()

    label = "paused" if new_val else "resumed"
    logger.info("User %s %s trading", user["id"], label)
    await callback.answer(f"Trading {label}!")
    await callback.message.edit_text(
        _format_settings({**user, "is_paused": new_val}),
        reply_markup=_settings_kb(new_val),
    )


# ── Edit trade size ──────────────────────────────────────────────────

@router.callback_query(F.data == "set_edit:trade_size")
async def on_edit_trade_size(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsEdit.waiting_trade_size)
    await callback.message.edit_text("Enter new trade size in USD (e.g. <code>5</code>):")


@router.message(SettingsEdit.waiting_trade_size)
async def on_trade_size_input(message: Message, state: FSMContext) -> None:
    try:
        size = float(message.text.strip().replace("$", ""))
        if size < 1 or size > 100:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Enter a valid amount between 1 and 100.")
        return

    sb = get_supabase()
    sb.table("users").update({"max_trade_size": size}).eq(
        "telegram_id", message.from_user.id
    ).execute()
    await state.clear()
    await message.answer(f"Trade size updated to <b>${size:.2f}</b>.")


# ── Edit fee rate ─────────────────────────────────────────────────────

@router.callback_query(F.data == "set_edit:fee_rate")
async def on_edit_fee_rate(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsEdit.waiting_fee_rate)
    await callback.message.edit_text("Enter new fee rate as percentage (e.g. <code>2.5</code>):")


@router.message(SettingsEdit.waiting_fee_rate)
async def on_fee_rate_input(message: Message, state: FSMContext) -> None:
    try:
        pct = float(message.text.strip().replace("%", ""))
        if pct < 1 or pct > 20:
            raise ValueError
        rate = round(pct / 100, 4)
    except (ValueError, AttributeError):
        await message.answer("Enter a valid percentage between 1 and 20.")
        return

    sb = get_supabase()
    sb.table("users").update({"trade_fee_rate": rate}).eq(
        "telegram_id", message.from_user.id
    ).execute()
    await state.clear()
    await message.answer(f"Fee rate updated to <b>{pct:.1f}%</b>.")


# ── Edit max trades per day ───────────────────────────────────────────

@router.callback_query(F.data == "set_edit:max_trades")
async def on_edit_max_trades(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SettingsEdit.waiting_max_trades)
    await callback.message.edit_text("Enter max trades per day (e.g. <code>30</code>):")


@router.message(SettingsEdit.waiting_max_trades)
async def on_max_trades_input(message: Message, state: FSMContext) -> None:
    try:
        val = int(message.text.strip())
        if val < 1 or val > 200:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Enter a number between 1 and 200.")
        return

    sb = get_supabase()
    sb.table("users").update({"max_trades_per_day": val}).eq(
        "telegram_id", message.from_user.id
    ).execute()
    await state.clear()
    await message.answer(f"Max trades per day updated to <b>{val}</b>.")
