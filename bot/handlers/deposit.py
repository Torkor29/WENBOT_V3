"""Deposit helper — /deposit command to explain how to fund the wallet."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes

from bot.config import settings
from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id


def _build_transak_url(wallet_address: str) -> str:
    """Build a Transak URL prefilled for USDC on Polygon."""
    if not settings.transak_api_key:
        # Public widget without API key (less control, but works for basic flows)
        base = "https://global.transak.com/"
        return (
            f"{base}?cryptoCurrencyCode=USDC&network=polygon&walletAddress={wallet_address}"
        )

    base = "https://global.transak.com/"
    return (
        f"{base}?apiKey={settings.transak_api_key}"
        f"&cryptoCurrencyCode=USDC"
        f"&network=polygon"
        f"&walletAddress={wallet_address}"
    )


async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain how to deposit USDC on Polygon to the user's wallet."""
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user or not user.wallet_address:
            await update.message.reply_text(
                "❌ Wallet non configuré. Utilisez /start pour vous inscrire "
                "et créer ou importer un wallet Polygon."
            )
            return

        wallet = user.wallet_address
        short_wallet = f"{wallet[:6]}...{wallet[-4:]}"
        transak_url = _build_transak_url(wallet)

    text = (
        "💳 **DÉPOSER DES USDC SUR VOTRE WALLET**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📬 Votre adresse Polygon : `{wallet}`\n\n"
        "Vous avez plusieurs options pour déposer des fonds :\n\n"
        "1️⃣ **Carte bancaire (recommandé pour débuter)**\n"
        "   → Achetez des USDC et recevez-les directement sur votre wallet Polygon.\n\n"
        "2️⃣ **Depuis un exchange (Binance, OKX, Bybit, etc.)**\n"
        "   → Retrait en **USDC sur le réseau Polygon** vers votre adresse.\n\n"
        "3️⃣ **Bridge SOL → USDC**\n"
        "   → Si vous avez du SOL, utilisez la commande /bridge.\n\n"
        "⚠️ Pensez à garder un peu de **POL/MATIC** sur Polygon pour les frais de gas "
        "(quelques centimes suffisent)."
    )

    keyboard = [
        [
            InlineKeyboardButton("💳 Acheter USDC (carte)", url=transak_url),
        ],
        [
            InlineKeyboardButton(
                "📋 Copier l'adresse", callback_data="deposit_copy_address"
            )
        ],
        [
            InlineKeyboardButton("🌉 Bridge SOL → USDC", callback_data="cmd_bridge"),
        ],
    ]

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def get_deposit_handler() -> CommandHandler:
    """Return the /deposit command handler."""
    return CommandHandler("deposit", deposit_command)

