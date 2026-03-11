"""Bridge handler — /bridge command for SOL → USDC Polygon bridging."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id
from bot.services.bridge import get_best_quote, execute_bridge, BridgeProvider
from bot.services.crypto import decrypt_private_key
from bot.config import settings
from bot.handlers.notifications import format_bridge_notification

logger = logging.getLogger(__name__)

AMOUNT_INPUT, CONFIRM_BRIDGE = range(2)


async def bridge_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start bridge flow — /bridge."""
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await update.message.reply_text("❌ Compte non trouvé. /start")
            return ConversationHandler.END

        if not user.solana_wallet_address:
            await update.message.reply_text(
                "❌ **Aucun wallet Solana configuré.**\n\n"
                "Ajoutez votre wallet Solana dans /settings pour utiliser le bridge.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

    await update.message.reply_text(
        "🌉 **Bridge SOL → USDC Polygon**\n\n"
        "Combien de SOL voulez-vous bridger ?\n\n"
        "Envoyez le montant (ex: `1.5`) :",
        parse_mode="Markdown",
    )
    return AMOUNT_INPUT


async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive SOL amount and get quote."""
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Montant invalide. Envoyez un nombre (ex: `1.5`).")
        return AMOUNT_INPUT

    if amount <= 0 or amount > 1000:
        await update.message.reply_text("❌ Montant entre 0.01 et 1000 SOL.")
        return AMOUNT_INPUT

    # Show typing indicator
    await update.effective_chat.send_action("typing")

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, update.effective_user.id)
        sol_wallet = user.solana_wallet_address
        poly_wallet = user.wallet_address or sol_wallet

    # Get best quote
    quote = await get_best_quote(amount, sol_wallet, poly_wallet)

    if not quote:
        await update.message.reply_text(
            "❌ **Impossible d'obtenir un devis.**\n\n"
            "Les providers de bridge sont indisponibles. Réessayez plus tard.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    context.user_data["bridge_quote"] = quote
    context.user_data["bridge_amount"] = amount

    provider_name = "Li.Fi" if quote.provider == BridgeProvider.LIFI else "Across"
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmer le bridge", callback_data="bridge_confirm"),
            InlineKeyboardButton("❌ Annuler", callback_data="bridge_cancel"),
        ]
    ]

    await update.message.reply_text(
        "🌉 **Devis Bridge**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"☀️ Envoi      : **{amount:.4f} SOL** (Solana)\n"
        f"💵 Réception  : **~{quote.output_amount:.2f} USDC** (Polygon)\n"
        f"🔄 Provider   : **{provider_name}**\n"
        f"💸 Frais      : **~{quote.fee_usd:.2f} USD**\n"
        f"⏱️ Estimé     : **~{quote.estimated_time_seconds // 60} min**\n"
        f"📊 Slippage   : **{settings.bridge_slippage * 100:.1f}%**\n\n"
        "Confirmer le bridge ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CONFIRM_BRIDGE


async def bridge_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Execute the bridge."""
    query = update.callback_query
    await query.answer()

    quote = context.user_data.get("bridge_quote")
    if not quote:
        await query.edit_message_text("❌ Erreur — devis expiré. Relancez /bridge.")
        return ConversationHandler.END

    await query.edit_message_text(
        "🟡 **Bridge en cours...**\n\n"
        "⏳ Signature et soumission de la transaction...",
        parse_mode="Markdown",
    )

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, query.from_user.id)
        if not user or not user.encrypted_solana_key:
            await query.edit_message_text("❌ Erreur — clé Solana manquante.")
            return ConversationHandler.END

        try:
            pk = decrypt_private_key(
                user.encrypted_solana_key,
                settings.encryption_key,
                user.uuid,
            )
        except Exception:
            await query.edit_message_text("❌ Erreur de déchiffrement de la clé Solana.")
            return ConversationHandler.END

    result = await execute_bridge(quote, pk)

    if result.success:
        text = format_bridge_notification(
            amount_sol=quote.input_amount,
            amount_usdc=result.output_amount,
            bridge_provider=quote.provider.value,
            fee_usd=result.fee_usd,
            tx_hash=result.tx_hash or "pending",
            status="completed",
        )
    else:
        text = (
            "🔴 **Bridge échoué**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ Erreur : {result.error}\n\n"
            "Réessayez avec /bridge."
        )

    await query.edit_message_text(text, parse_mode="Markdown")

    context.user_data.pop("bridge_quote", None)
    context.user_data.pop("bridge_amount", None)
    return ConversationHandler.END


async def bridge_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel bridge."""
    query = update.callback_query
    await query.answer()

    context.user_data.pop("bridge_quote", None)
    context.user_data.pop("bridge_amount", None)

    await query.edit_message_text("❌ Bridge annulé.")
    return ConversationHandler.END


def get_bridge_handler() -> ConversationHandler:
    """Build the /bridge conversation handler."""
    return ConversationHandler(
        entry_points=[CommandHandler("bridge", bridge_command)],
        states={
            AMOUNT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount),
            ],
            CONFIRM_BRIDGE: [
                CallbackQueryHandler(bridge_confirm, pattern="^bridge_confirm$"),
                CallbackQueryHandler(bridge_cancel, pattern="^bridge_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("bridge", bridge_command)],
        per_user=True,
    )
