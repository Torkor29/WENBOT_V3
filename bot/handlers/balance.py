"""Balance handler — /balance, /positions, /history commands."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes
from sqlalchemy import select, func

from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id
from bot.models.trade import Trade, TradeStatus

logger = logging.getLogger(__name__)


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's balance — redirects to the menu Wallets view.

    La commande /balance est conservée pour rétro-compatibilité, mais
    renvoie vers le même affichage que le bouton « 👛 Wallets » du menu.
    """
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await update.message.reply_text(
                "❌ Compte non trouvé. Utilisez /start pour vous inscrire."
            )
            return

        if not user.wallet_address:
            await update.message.reply_text(
                "👛 **Wallet non configuré**\n\n"
                "Utilisez /start puis « 🧭 Configurer mon wallet » "
                "pour créer ou importer un wallet.",
                parse_mode="Markdown",
            )
            return

        from bot.services.web3_client import polygon_client
        usdc_native, usdc_e = await polygon_client.get_usdc_balances(user.wallet_address)
        pol = await polygon_client.get_matic_balance(user.wallet_address)

        w = user.wallet_address
        wallet_short = f"`{w[:6]}...{w[-4:]}`"

    text = (
        "👛 **SOLDES**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📬 Wallet : {wallet_short}\n"
        f"💵 USDC natif : **{usdc_native:.2f}**\n"
        f"💵 USDC.e : **{usdc_e:.2f}**\n"
        f"⛽ POL (gas) : **{pol:.4f}**\n\n"
        "💡 Utilisez le menu principal pour plus d'options."
    )

    keyboard = [
        [
            InlineKeyboardButton("💳 Déposer", callback_data="menu_deposit"),
            InlineKeyboardButton("💸 Retirer", callback_data="menu_withdraw"),
        ],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show active copytrading positions."""
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await update.message.reply_text("❌ Compte non trouvé. /start pour s'inscrire.")
            return

        result = await session.execute(
            select(Trade)
            .where(
                Trade.user_id == user.id,
                Trade.status == TradeStatus.FILLED,
            )
            .order_by(Trade.created_at.desc())
            .limit(20)
        )
        trades = result.scalars().all()

    if not trades:
        await update.message.reply_text(
            "📊 **Positions actives**\n\n"
            "Aucune position ouverte pour le moment.\n"
            "Les trades seront copiés automatiquement quand le master tradera.",
            parse_mode="Markdown",
        )
        return

    lines = ["📊 **POSITIONS ACTIVES**\n━━━━━━━━━━━━━━━━━━━━\n"]
    for t in trades:
        emoji = "🟢" if t.side.value == "buy" else "🔴"
        question = t.market_question or t.market_id
        if len(question) > 40:
            question = question[:37] + "..."
        lines.append(
            f"{emoji} **{question}**\n"
            f"   {t.side.value.upper()} @ {t.price:.2f} | "
            f"Net: {t.net_amount_usdc:.2f} USDC | "
            f"Shares: {t.shares:.1f}\n"
        )

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown"
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show trade history with P&L and fees."""
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await update.message.reply_text("❌ Compte non trouvé. /start pour s'inscrire.")
            return

        result = await session.execute(
            select(Trade)
            .where(Trade.user_id == user.id)
            .order_by(Trade.created_at.desc())
            .limit(20)
        )
        trades = result.scalars().all()

        # Total fees
        from bot.models.fee import FeeRecord
        total_fees = await session.scalar(
            select(func.sum(FeeRecord.fee_amount)).where(
                FeeRecord.user_id == user.id,
            )
        ) or 0.0

    if not trades:
        await update.message.reply_text(
            "📜 **Historique des trades**\n\nAucun trade enregistré.",
            parse_mode="Markdown",
        )
        return

    lines = [
        "📜 **HISTORIQUE DES TRADES**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    ]

    status_emoji = {
        TradeStatus.FILLED: "✅",
        TradeStatus.FAILED: "❌",
        TradeStatus.CANCELLED: "🚫",
        TradeStatus.PENDING: "🟡",
        TradeStatus.EXECUTING: "🔄",
    }

    for t in trades:
        emoji = status_emoji.get(t.status, "❓")
        question = t.market_question or t.market_id
        if len(question) > 35:
            question = question[:32] + "..."
        date_str = t.created_at.strftime("%d/%m %H:%M") if t.created_at else "?"
        paper = " 📝" if t.is_paper else ""
        lines.append(
            f"{emoji} {date_str} | {t.side.value.upper()} | "
            f"{t.net_amount_usdc:.2f} USDC | "
            f"Fee: {t.fee_amount_usdc:.2f}{paper}\n"
            f"   {question}\n"
        )

    lines.append(f"\n💸 **Total frais payés : {total_fees:.2f} USDC**")

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown"
    )


def get_balance_handlers() -> list:
    """Return all balance-related command handlers."""
    return [
        CommandHandler("balance", balance_command),
        CommandHandler("positions", positions_command),
        CommandHandler("history", history_command),
    ]
