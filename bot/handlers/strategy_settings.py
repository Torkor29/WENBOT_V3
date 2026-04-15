"""Strategy settings handler — fee rate, max trades, pause, wallet setup."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters
from sqlalchemy import select

from bot.config import settings
from bot.db.session import async_session
from bot.models.strategy_user_settings import StrategyUserSettings
from bot.services.user_service import get_user_by_telegram_id

logger = logging.getLogger(__name__)

# State key for pending setting edit
_PENDING_KEY = "_strat_setting_pending"


async def strat_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show strategy settings overview."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await query.edit_message_text("❌ Compte non trouvé.")
            return

        sus = (
            await session.execute(
                select(StrategyUserSettings).where(
                    StrategyUserSettings.user_id == user.id
                )
            )
        ).scalar_one_or_none()

    if not sus:
        fee_rate = 0.01
        max_trades = 50
        paused = False
    else:
        fee_rate = sus.trade_fee_rate
        max_trades = sus.max_trades_per_day
        paused = sus.is_paused

    status = "🟡 PAUSÉ" if paused else "🟢 ACTIF"
    wallet_short = (
        f"`{user.strategy_wallet_address[:6]}...{user.strategy_wallet_address[-4:]}`"
        if user.strategy_wallet_address else "Non configuré"
    )

    text = (
        "⚙️ *PARAMÈTRES STRATÉGIE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📬 Wallet : {wallet_short}\n"
        f"📊 Statut : {status}\n"
        f"💸 Fee rate : *{fee_rate*100:.1f}%*\n"
        f"📈 Max trades/jour : *{max_trades}*\n"
    )

    keyboard = [
        [InlineKeyboardButton(
            f"💸 Fee rate ({fee_rate*100:.1f}%)",
            callback_data="strat_set:fee_rate",
        )],
        [InlineKeyboardButton(
            f"📈 Max trades ({max_trades})",
            callback_data="strat_set:max_trades",
        )],
        [InlineKeyboardButton(
            "▶️ Reprendre" if paused else "⏸ Pause",
            callback_data="strat_set:toggle_pause",
        )],
    ]

    if not user.strategy_wallet_address:
        keyboard.append([InlineKeyboardButton(
            "🆕 Créer wallet stratégie", callback_data="strat_create_wallet",
        )])

    keyboard.append([
        InlineKeyboardButton("⬅️ Stratégies", callback_data="hub_strat"),
        InlineKeyboardButton("🏠 Accueil", callback_data="hub_home"),
    ])

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def strat_set_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings edits via callbacks."""
    query = update.callback_query
    await query.answer()

    field = query.data.split(":")[1]
    tg_user = update.effective_user

    if field == "toggle_pause":
        async with async_session() as session:
            user = await get_user_by_telegram_id(session, tg_user.id)
            if not user:
                return

            sus = (
                await session.execute(
                    select(StrategyUserSettings).where(
                        StrategyUserSettings.user_id == user.id
                    )
                )
            ).scalar_one_or_none()

            if not sus:
                sus = StrategyUserSettings(user_id=user.id)
                session.add(sus)

            sus.is_paused = not sus.is_paused
            await session.commit()
            new_state = "⏸ Pausé" if sus.is_paused else "▶️ Actif"

        await query.edit_message_text(
            f"✅ Stratégies : *{new_state}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="strat_settings")],
            ]),
        )
        return

    if field == "fee_rate":
        context.user_data[_PENDING_KEY] = "fee_rate"
        await query.edit_message_text(
            "💸 Entrez le nouveau taux de fee (1-20%) :\n"
            "Exemple: `2.5`",
            parse_mode="Markdown",
        )
        return

    if field == "max_trades":
        context.user_data[_PENDING_KEY] = "max_trades"
        await query.edit_message_text(
            "📈 Entrez le nombre max de trades par jour (1-200) :\n"
            "Exemple: `50`",
            parse_mode="Markdown",
        )
        return


async def strat_set_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input for strategy settings."""
    pending = context.user_data.get(_PENDING_KEY)
    if not pending:
        return  # Not waiting for strategy setting input

    tg_user = update.effective_user
    text = update.message.text.strip()

    if pending == "fee_rate":
        try:
            pct = float(text.replace("%", ""))
        except ValueError:
            await update.message.reply_text("❌ Nombre invalide.")
            return

        if pct < 1.0 or pct > 20.0:
            await update.message.reply_text("❌ Fee entre 1% et 20%.")
            return

        fee_rate = round(pct / 100, 4)

        async with async_session() as session:
            user = await get_user_by_telegram_id(session, tg_user.id)
            if not user:
                return

            sus = (
                await session.execute(
                    select(StrategyUserSettings).where(
                        StrategyUserSettings.user_id == user.id
                    )
                )
            ).scalar_one_or_none()

            if not sus:
                sus = StrategyUserSettings(user_id=user.id, trade_fee_rate=fee_rate)
                session.add(sus)
            else:
                sus.trade_fee_rate = fee_rate
            await session.commit()

        context.user_data.pop(_PENDING_KEY, None)
        await update.message.reply_text(
            f"✅ Fee rate mis à jour : *{pct:.1f}%*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="strat_settings")],
            ]),
        )

    elif pending == "max_trades":
        try:
            val = int(text)
        except ValueError:
            await update.message.reply_text("❌ Nombre invalide.")
            return

        if val < 1 or val > 200:
            await update.message.reply_text("❌ Entre 1 et 200.")
            return

        async with async_session() as session:
            user = await get_user_by_telegram_id(session, tg_user.id)
            if not user:
                return

            sus = (
                await session.execute(
                    select(StrategyUserSettings).where(
                        StrategyUserSettings.user_id == user.id
                    )
                )
            ).scalar_one_or_none()

            if not sus:
                sus = StrategyUserSettings(user_id=user.id, max_trades_per_day=val)
                session.add(sus)
            else:
                sus.max_trades_per_day = val
            await session.commit()

        context.user_data.pop(_PENDING_KEY, None)
        await update.message.reply_text(
            f"✅ Max trades/jour : *{val}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="strat_settings")],
            ]),
        )


def get_strategy_settings_handlers() -> list:
    """Return handlers for strategy settings."""
    return [
        CallbackQueryHandler(strat_settings_menu, pattern="^strat_settings$"),
        CallbackQueryHandler(strat_set_handler, pattern=r"^strat_set:"),
        MessageHandler(filters.TEXT & ~filters.COMMAND, strat_set_input),
    ]
