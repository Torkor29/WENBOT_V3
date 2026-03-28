"""Admin panel handler — /admin command (admin only).

Refonte V3 : metrics enrichis, segmentation users, barres visuelles.
"""

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


def _admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Followers", callback_data="admin_followers"),
            InlineKeyboardButton("💰 Frais", callback_data="admin_fees"),
        ],
        [
            InlineKeyboardButton("📊 Trades", callback_data="admin_trades"),
            InlineKeyboardButton("🧠 V3 Stats", callback_data="admin_v3"),
        ],
        [InlineKeyboardButton("🔄 Rafraîchir", callback_data="admin_refresh")],
    ])


async def _build_admin_text(session) -> str:
    """Build admin dashboard text with rich metrics."""
    from bot.utils.formatting import header, fmt_usd, bar, SEP
    from bot.models.user import User, UserRole
    from sqlalchemy import select, func

    stats = await get_admin_stats(session)

    # User segmentation
    all_users = (await session.execute(
        select(User).where(User.role == UserRole.FOLLOWER)
    )).scalars().all()

    active = [u for u in all_users if u.is_active and not u.is_paused]
    paused = [u for u in all_users if u.is_paused]
    inactive = [u for u in all_users if not u.is_active]
    live_users = [u for u in all_users if not u.paper_trading]
    paper_users = [u for u in all_users if u.paper_trading]
    total = len(all_users)

    # Visual bars
    active_pct = (len(active) / total * 100) if total > 0 else 0
    live_pct = (len(live_users) / total * 100) if total > 0 else 0

    return (
        f"{header('PANEL ADMIN', '📊')}\n\n"
        f"👥 *Users:* {total} total\n"
        f"  🟢 Actifs: *{len(active)}* | 🟡 Pause: *{len(paused)}* | ⚫ Inactifs: *{len(inactive)}*\n"
        f"  {bar(active_pct, 100, 10)} {active_pct:.0f}% actifs\n"
        f"  💵 Live: *{len(live_users)}* | 📝 Paper: *{len(paper_users)}*\n"
        f"  {bar(live_pct, 100, 10)} {live_pct:.0f}% en live\n\n"
        f"📊 *Volume & Revenus:*\n"
        f"  🔄 Trades (mois): *{stats['trade_count']}*\n"
        f"  💰 Volume: *{fmt_usd(stats['total_volume'])}*\n"
        f"  🏦 Frais (1%): *{fmt_usd(stats['total_fees'])}*\n\n"
        f"💼 `{settings.fees_wallet}`"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin dashboard."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Accès refusé.")
        return

    async with async_session() as session:
        text = await _build_admin_text(session)

    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=_admin_keyboard()
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
            text = await _build_admin_text(session)
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=_admin_keyboard()
        )

    elif action == "followers":
        from bot.utils.formatting import short_wallet as sw
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
                "👥 *Aucun follower inscrit.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
                ]),
            )
            return

        from bot.utils.formatting import header, fmt_usd

        lines = [f"{header('FOLLOWERS', '👥')}\n"]
        for f in followers:
            status = "🟢" if f.is_active and not f.is_paused else ("🟡" if f.is_paused else "🔴")
            name = f"@{f.telegram_username}" if f.telegram_username else str(f.telegram_id)
            mode = "💵" if not f.paper_trading else "📝"
            vol = f.daily_spent_usdc or 0
            lines.append(
                f"{status} {mode} *{name}* | Jour: {fmt_usd(vol)}/{fmt_usd(f.daily_limit_usdc)}"
            )

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
            ]),
        )

    elif action == "fees":
        from bot.utils.formatting import header, fmt_usd, bar
        from bot.models.fee import FeeRecord
        from sqlalchemy import select, func

        async with async_session() as session:
            total = await session.scalar(
                select(func.sum(FeeRecord.fee_amount))
            ) or 0.0
            confirmed = await session.scalar(
                select(func.sum(FeeRecord.fee_amount)).where(
                    FeeRecord.confirmed_on_chain == True  # noqa
                )
            ) or 0.0
            paper = await session.scalar(
                select(func.sum(FeeRecord.fee_amount)).where(
                    FeeRecord.is_paper == True  # noqa
                )
            ) or 0.0
            count = await session.scalar(
                select(func.count(FeeRecord.id))
            ) or 0

        live_fees = total - paper
        live_pct = (live_fees / total * 100) if total > 0 else 0

        await query.edit_message_text(
            f"{header('DÉTAIL FRAIS', '💰')}\n\n"
            f"📊 *{count}* prélèvements | Total: *{fmt_usd(total)}*\n\n"
            f"💵 Live (on-chain): *{fmt_usd(live_fees)}* ({live_pct:.0f}%)\n"
            f"  ✅ Confirmés: *{fmt_usd(confirmed)}*\n"
            f"📝 Paper (simulés): *{fmt_usd(paper)}*\n"
            f"  {bar(live_pct, 100, 10)} {live_pct:.0f}% live\n\n"
            f"💼 `{settings.fees_wallet}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
            ]),
        )

    elif action == "trades":
        from bot.utils.formatting import header, fmt_usd
        from bot.models.trade import Trade
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(Trade).order_by(Trade.created_at.desc()).limit(10)
            )
            trades = result.scalars().all()

        if not trades:
            await query.edit_message_text(
                f"{header('TRADES RÉCENTS', '📊')}\n\nAucun trade.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
                ]),
            )
            return

        lines = [f"{header('TRADES RÉCENTS', '📊')}\n"]
        for t in trades:
            date = t.created_at.strftime("%d/%m %H:%M") if t.created_at else "?"
            mode = "📝" if t.is_paper else "💵"
            side = "🟢" if t.side.value == "buy" else "🔴"
            status_map = {"filled": "✅", "failed": "❌", "cancelled": "🚫", "pending": "🟡", "executing": "🔄"}
            st = status_map.get(t.status.value, "❓")
            lines.append(
                f"{mode}{side} {date} | {fmt_usd(t.net_amount_usdc)} | {st} {t.status.value}"
            )

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Retour", callback_data="admin_refresh")],
            ]),
        )

    elif action == "v3":
        from bot.utils.formatting import header, bar
        from bot.models.signal_score import SignalScore
        from bot.models.active_position import ActivePosition
        from bot.models.trader_stats import TraderStats
        from sqlalchemy import select, func

        async with async_session() as session:
            # Signal stats
            total_signals = await session.scalar(
                select(func.count(SignalScore.id))
            ) or 0
            avg_score = await session.scalar(
                select(func.avg(SignalScore.total_score))
            ) or 0
            passed = await session.scalar(
                select(func.count(SignalScore.id)).where(SignalScore.passed == True)  # noqa
            ) or 0

            # Active positions
            open_positions = await session.scalar(
                select(func.count(ActivePosition.id)).where(
                    ActivePosition.is_closed == False  # noqa
                )
            ) or 0
            closed_sl = await session.scalar(
                select(func.count(ActivePosition.id)).where(
                    ActivePosition.close_reason == "sl_hit"
                )
            ) or 0
            closed_tp = await session.scalar(
                select(func.count(ActivePosition.id)).where(
                    ActivePosition.close_reason == "tp_hit"
                )
            ) or 0

            # Tracked traders
            tracked = await session.scalar(
                select(func.count(func.distinct(TraderStats.wallet)))
            ) or 0
            hot = await session.scalar(
                select(func.count(TraderStats.id)).where(
                    TraderStats.is_hot == True, TraderStats.period == "7d"  # noqa
                )
            ) or 0
            cold = await session.scalar(
                select(func.count(TraderStats.id)).where(
                    TraderStats.is_cold == True, TraderStats.period == "7d"  # noqa
                )
            ) or 0

        block_rate = ((total_signals - passed) / total_signals * 100) if total_signals > 0 else 0

        await query.edit_message_text(
            f"{header('V3 SMART ANALYSIS', '🧠')}\n\n"
            f"*Scoring:*\n"
            f"  📊 {total_signals} signaux analysés\n"
            f"  🎯 Score moyen: *{avg_score:.0f}/100*\n"
            f"  {bar(100 - block_rate, 100, 10)} {100 - block_rate:.0f}% acceptés / {block_rate:.0f}% bloqués\n\n"
            f"*Positions actives:*\n"
            f"  📦 {open_positions} ouvertes\n"
            f"  🔴 {closed_sl} SL déclenchés | 🟢 {closed_tp} TP atteints\n\n"
            f"*Traders trackés:*\n"
            f"  👤 {tracked} traders | 🔥 {hot} hot | 🥶 {cold} cold",
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
