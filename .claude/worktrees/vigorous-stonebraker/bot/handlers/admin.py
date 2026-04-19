"""Admin panel handler — /admin command (admin only)."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

from bot.config import settings
from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id, get_admin_stats

logger = logging.getLogger(__name__)


def is_admin(telegram_id: int) -> bool:
    """Check if user is admin by telegram ID."""
    try:
        return str(telegram_id) == str(settings.admin_chat_id)
    except (ValueError, AttributeError):
        return False


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin dashboard."""
    tg_user = update.effective_user

    if not is_admin(tg_user.id):
        await update.message.reply_text("🚫 Accès refusé — admin uniquement.")
        return

    async with async_session() as session:
        stats = await get_admin_stats(session)

    await update.message.reply_text(
        "📊 **PANEL ADMIN**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Followers actifs   : **{stats['follower_count']}**\n"
        f"🔄 Trades ce mois     : **{stats['trade_count']}**\n"
        f"💰 Volume total       : **{stats['total_volume']:.2f} USDC**\n"
        f"🏦 Revenus frais (1%) : **{stats['total_fees']:.2f} USDC**\n\n"
        f"💼 Fees Wallet : `{settings.fees_wallet}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👥 Followers", callback_data="admin_followers"),
                InlineKeyboardButton("💰 Détail frais", callback_data="admin_fees"),
            ],
            [
                InlineKeyboardButton("📊 Trades récents", callback_data="admin_trades"),
                InlineKeyboardButton("🔄 Rafraîchir", callback_data="admin_refresh"),
            ],
        ]),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin panel button presses."""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    action = query.data.replace("admin_", "")

    if action == "refresh":
        async with async_session() as session:
            stats = await get_admin_stats(session)
        await query.edit_message_text(
            "📊 **PANEL ADMIN** (mis à jour)\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Followers actifs   : **{stats['follower_count']}**\n"
            f"🔄 Trades ce mois     : **{stats['trade_count']}**\n"
            f"💰 Volume total       : **{stats['total_volume']:.2f} USDC**\n"
            f"🏦 Revenus frais (1%) : **{stats['total_fees']:.2f} USDC**",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👥 Followers", callback_data="admin_followers"),
                    InlineKeyboardButton("💰 Détail frais", callback_data="admin_fees"),
                ],
                [InlineKeyboardButton("🔄 Rafraîchir", callback_data="admin_refresh")],
            ]),
        )

    elif action == "followers":
        from bot.models.user import User, UserRole
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(User)
                .where(User.role == UserRole.FOLLOWER)
                .order_by(User.created_at.desc())
                .limit(20)
            )
            followers = result.scalars().all()

        if not followers:
            await query.edit_message_text(
                "👥 **Aucun follower inscrit.**",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
                ]),
            )
            return

        lines = ["👥 **FOLLOWERS**\n━━━━━━━━━━━━━━━━━━━━\n"]
        for f in followers:
            status = "🟢" if f.is_active and not f.is_paused else "🟡" if f.is_paused else "🔴"
            name = f.telegram_username or str(f.telegram_id)
            mode = "📝" if f.paper_trading else "💵"
            lines.append(f"{status} {name} {mode} | Limit: {f.daily_limit_usdc} USDC")

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
            ]),
        )

    elif action == "fees":
        from bot.models.fee import FeeRecord
        from sqlalchemy import select, func

        async with async_session() as session:
            total = await session.scalar(
                select(func.sum(FeeRecord.fee_amount))
            ) or 0.0

            confirmed = await session.scalar(
                select(func.sum(FeeRecord.fee_amount)).where(
                    FeeRecord.confirmed_on_chain == True
                )
            ) or 0.0

            paper = await session.scalar(
                select(func.sum(FeeRecord.fee_amount)).where(
                    FeeRecord.is_paper == True
                )
            ) or 0.0

            count = await session.scalar(
                select(func.count(FeeRecord.id))
            ) or 0

        await query.edit_message_text(
            "💰 **DÉTAIL DES FRAIS**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Nombre de prélèvements : **{count}**\n"
            f"💵 Total frais             : **{total:.2f} USDC**\n"
            f"✅ Confirmés on-chain      : **{confirmed:.2f} USDC**\n"
            f"📝 Paper (simulés)         : **{paper:.2f} USDC**\n\n"
            f"💼 Wallet frais : `{settings.fees_wallet}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
            ]),
        )

    elif action == "trades":
        from bot.models.trade import Trade
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(Trade).order_by(Trade.created_at.desc()).limit(10)
            )
            trades = result.scalars().all()

        if not trades:
            await query.edit_message_text(
                "📊 **Aucun trade récent.**",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
                ]),
            )
            return

        lines = ["📊 **TRADES RÉCENTS**\n━━━━━━━━━━━━━━━━━━━━\n"]
        for t in trades:
            date = t.created_at.strftime("%d/%m %H:%M") if t.created_at else "?"
            lines.append(
                f"{'📝' if t.is_paper else '💵'} {date} | "
                f"{t.side.value.upper()} | {t.gross_amount_usdc:.2f} → "
                f"{t.net_amount_usdc:.2f} USDC | {t.status.value}"
            )

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
            ]),
        )


def get_admin_handlers() -> list:
    """Return admin command and callback handlers."""
    return [
        CommandHandler("admin", admin_command),
        CallbackQueryHandler(admin_callback, pattern="^admin_"),
    ]
