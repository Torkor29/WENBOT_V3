"""/subscribe flow – multi-step FSM."""

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


class SubscribeFlow(StatesGroup):
    choosing_strategy = State()
    choosing_trade_size = State()
    choosing_fee_rate = State()
    confirming = State()


# ── Step 1: list strategies ───────────────────────────────────────────

def _strategies_kb(strategies: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=s["name"], callback_data=f"sub_pick:{s['id']}")]
        for s in strategies
    ]
    buttons.append([InlineKeyboardButton(text="Cancel", callback_data="sub_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, state: FSMContext) -> None:
    sb = get_supabase()
    resp = (
        sb.table("strategies")
        .select("*")
        .eq("status", "active")
        .eq("visibility", "public")
        .execute()
    )
    strategies = resp.data or []
    if not strategies:
        await message.answer("No active strategies available right now.")
        return

    await state.set_state(SubscribeFlow.choosing_strategy)
    await message.answer(
        "Choose a strategy to subscribe to:",
        reply_markup=_strategies_kb(strategies),
    )


# ── Step 2: pick strategy → choose trade size ────────────────────────

_TRADE_SIZE_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="$2", callback_data="sub_size:2"),
            InlineKeyboardButton(text="$4", callback_data="sub_size:4"),
            InlineKeyboardButton(text="$6", callback_data="sub_size:6"),
        ],
        [InlineKeyboardButton(text="Custom amount", callback_data="sub_size:custom")],
        [InlineKeyboardButton(text="Cancel", callback_data="sub_cancel")],
    ]
)


@router.callback_query(F.data.startswith("sub_pick:"))
async def on_strategy_picked(callback: CallbackQuery, state: FSMContext) -> None:
    strategy_id = callback.data.split(":", 1)[1]
    await state.update_data(strategy_id=strategy_id)

    # Fetch strategy name for display
    sb = get_supabase()
    resp = sb.table("strategies").select("name").eq("id", strategy_id).execute()
    name = resp.data[0]["name"] if resp.data else strategy_id
    await state.update_data(strategy_name=name)

    await state.set_state(SubscribeFlow.choosing_trade_size)
    await callback.answer()
    await callback.message.edit_text(
        f"Strategy: <b>{name}</b>\n\nChoose your trade size:",
        reply_markup=_TRADE_SIZE_KB,
    )


# ── Step 2b: custom trade size (text input) ──────────────────────────

@router.callback_query(F.data == "sub_size:custom", SubscribeFlow.choosing_trade_size)
async def on_custom_size_request(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "Enter your custom trade size in USD (e.g. <code>5</code>):"
    )


@router.message(SubscribeFlow.choosing_trade_size)
async def on_custom_size_text(message: Message, state: FSMContext) -> None:
    try:
        size = float(message.text.strip().replace("$", ""))
        if size < 1 or size > 100:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Please enter a valid amount between 1 and 100.")
        return
    await state.update_data(trade_size=size)
    await _ask_fee_rate(message.answer, state)


# ── Step 2a: preset trade size ────────────────────────────────────────

@router.callback_query(F.data.startswith("sub_size:"), SubscribeFlow.choosing_trade_size)
async def on_trade_size_picked(callback: CallbackQuery, state: FSMContext) -> None:
    size = float(callback.data.split(":", 1)[1])
    await state.update_data(trade_size=size)
    await callback.answer()
    await _ask_fee_rate(callback.message.edit_text, state)


# ── Step 3: choose fee rate ───────────────────────────────────────────

_FEE_RATE_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="1%", callback_data="sub_fee:0.01"),
            InlineKeyboardButton(text="2%", callback_data="sub_fee:0.02"),
            InlineKeyboardButton(text="3%", callback_data="sub_fee:0.03"),
            InlineKeyboardButton(text="5%", callback_data="sub_fee:0.05"),
        ],
        [InlineKeyboardButton(text="Custom %", callback_data="sub_fee:custom")],
        [InlineKeyboardButton(text="Cancel", callback_data="sub_cancel")],
    ]
)


async def _ask_fee_rate(reply_func, state: FSMContext) -> None:
    await state.set_state(SubscribeFlow.choosing_fee_rate)
    await reply_func(
        "Choose your trade fee rate:\n\n"
        "<i>The higher the fee, the higher your trade execution priority.</i>",
        reply_markup=_FEE_RATE_KB,
    )


@router.callback_query(F.data == "sub_fee:custom", SubscribeFlow.choosing_fee_rate)
async def on_custom_fee_request(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "Enter your custom fee rate as a percentage (e.g. <code>2.5</code>):"
    )


@router.message(SubscribeFlow.choosing_fee_rate)
async def on_custom_fee_text(message: Message, state: FSMContext) -> None:
    try:
        pct = float(message.text.strip().replace("%", ""))
        if pct < 1 or pct > 20:
            raise ValueError
        fee_rate = round(pct / 100, 4)
    except (ValueError, AttributeError):
        await message.answer("Please enter a valid percentage between 1 and 20.")
        return
    await state.update_data(trade_fee_rate=fee_rate)
    await _show_confirmation(message.answer, state)


@router.callback_query(F.data.startswith("sub_fee:"), SubscribeFlow.choosing_fee_rate)
async def on_fee_picked(callback: CallbackQuery, state: FSMContext) -> None:
    fee_rate = float(callback.data.split(":", 1)[1])
    await state.update_data(trade_fee_rate=fee_rate)
    await callback.answer()
    await _show_confirmation(callback.message.edit_text, state)


# ── Step 4: confirmation ─────────────────────────────────────────────

_CONFIRM_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Confirm", callback_data="sub_confirm"),
            InlineKeyboardButton(text="Cancel", callback_data="sub_cancel"),
        ]
    ]
)


async def _show_confirmation(reply_func, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(SubscribeFlow.confirming)
    fee_pct = data["trade_fee_rate"] * 100
    await reply_func(
        f"<b>Subscription Summary</b>\n\n"
        f"Strategy: <b>{data['strategy_name']}</b>\n"
        f"Trade size: <b>${data['trade_size']:.2f}</b>\n"
        f"Fee rate: <b>{fee_pct:.1f}%</b>\n\n"
        f"Confirm?",
        reply_markup=_CONFIRM_KB,
    )


@router.callback_query(F.data == "sub_confirm", SubscribeFlow.confirming)
async def on_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    telegram_id = callback.from_user.id
    sb = get_supabase()

    # Get user id
    user_resp = sb.table("users").select("id").eq("telegram_id", telegram_id).execute()
    if not user_resp.data:
        await callback.answer("Account not found. Use /start first.", show_alert=True)
        await state.clear()
        return

    user_id = user_resp.data[0]["id"]

    # Also update user-level trade_fee_rate
    sb.table("users").update({"trade_fee_rate": data["trade_fee_rate"]}).eq("id", user_id).execute()

    # Insert subscription
    sb.table("subscriptions").insert(
        {
            "user_id": user_id,
            "strategy_id": data["strategy_id"],
            "trade_size": data["trade_size"],
            "is_active": True,
        }
    ).execute()

    logger.info(
        "New subscription: user=%s strategy=%s size=%s fee=%s",
        user_id,
        data["strategy_id"],
        data["trade_size"],
        data["trade_fee_rate"],
    )

    await callback.answer()
    await callback.message.edit_text(
        f"Subscribed to <b>{data['strategy_name']}</b>!\n\n"
        f"Trade size: ${data['trade_size']:.2f}\n"
        f"Fee rate: {data['trade_fee_rate'] * 100:.1f}%\n\n"
        f"Make sure your wallet is funded with USDC.e. Use /deposit to see your address."
    )
    await state.clear()


# ── Cancel ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "sub_cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Cancelled.")
    await callback.message.edit_text("Subscription cancelled.")
