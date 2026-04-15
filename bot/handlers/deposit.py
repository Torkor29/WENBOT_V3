"""Deposit helper — /deposit with guide to send USDC from an exchange."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id

logger = logging.getLogger(__name__)


async def deposit_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show deposit instructions — send USDC from an exchange."""
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user or not user.wallet_address:
            await update.message.reply_text(
                "❌ Wallet non configuré. Utilisez /start pour vous inscrire."
            )
            return

        wallet = user.wallet_address
        auto = user.wallet_auto_created

    if auto:
        tag = "🏷️ *Wallet créé par le bot* — il est vide au départ."
    else:
        tag = "🏷️ *Wallet importé* — vos USDC existants sont déjà utilisables."

    text = (
        "💰 **DÉPOSER DES USDC**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{tag}\n\n"
        f"📬 Votre adresse Polygon :\n`{wallet}`\n\n"
        "**Comment faire :**\n\n"
        "1. Ouvrez votre exchange (Binance, Coinbase, OKX, Bybit…)\n"
        "2. Achetez des **USDC** si vous n'en avez pas (carte, virement…)\n"
        "3. Allez dans **Retrait / Withdraw**\n"
        "4. Sélectionnez **USDC**\n"
        "5. Collez l'adresse ci-dessus comme destination\n"
        "6. **IMPORTANT** — réseau : **Polygon**\n"
        "   ⚠️ Pas Ethereum, pas Arbitrum → **Polygon** uniquement !\n"
        "7. Confirmez le retrait\n\n"
        "⏱️ ~2-5 min • Frais : ~0.1 USDC\n\n"
        "💡 *Envoyez aussi ~0.2 POL/MATIC pour le gas "
        "(quelques centimes suffisent pour des dizaines de trades).*"
    )

    keyboard = [
        [InlineKeyboardButton(
            "📋 Copier mon adresse Polygon", callback_data="deposit_copy_address"
        )],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _deposit_copy_address(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, update.effective_user.id)
        if user and user.wallet_address:
            keyboard = [[InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")]]
            await query.message.reply_text(
                f"`{user.wallet_address}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await query.answer("Wallet non configuré", show_alert=True)


def get_deposit_handlers() -> list:
    return [
        CommandHandler("deposit", deposit_command),
        CallbackQueryHandler(
            _deposit_copy_address, pattern="^deposit_copy_address$"
        ),
    ]
