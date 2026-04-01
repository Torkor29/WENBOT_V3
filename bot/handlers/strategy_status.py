"""Strategy status handler — PnL summary, trade history, active subscriptions."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ContextTypes
from sqlalchemy import select, desc, func

from bot.db.session import async_session
from bot.models.subscription import Subscription
from bot.models.strategy import Strategy
from bot.models.trade import Trade, TradeStatus
from bot.services.user_service import get_user_by_telegram_id

logger = logging.getLogger(__name__)


async def strat_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show active subscriptions + PnL summary."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await query.edit_message_text("❌ Compte non trouvé.")
            return

        # Active subscriptions
        subs = (
            await session.execute(
                select(Subscription, Strategy)
                .join(Strategy, Subscription.strategy_id == Strategy.id)
                .where(
                    Subscription.user_id == user.id,
                    Subscription.is_active == True,  # noqa: E712
                )
            )
        ).all()

        # Strategy trades stats
        strat_trades = (
            await session.execute(
                select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.strategy_id.isnot(None),
                )
            )
        ).scalars().all()

    total_trades = len(strat_trades)
    resolved = [t for t in strat_trades if t.resolved_at]
    total_pnl = sum(t.pnl or 0 for t in resolved)
    wins = sum(1 for t in resolved if t.result == "WON")
    losses = len(resolved) - wins
    wr = (wins / len(resolved) * 100) if resolved else 0
    pending = total_trades - len(resolved)

    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    wallet_short = (
        f"`{user.strategy_wallet_address[:6]}...{user.strategy_wallet_address[-4:]}`"
        if user.strategy_wallet_address else "Non configuré"
    )

    lines = [
        "📊 *STATUT STRATÉGIES*",
        "━━━━━━━━━━━━━━━━━━━━\n",
        f"📬 Wallet stratégie: {wallet_short}",
        f"📊 Abonnements actifs: *{len(subs)}*",
        f"🔢 Total trades: {total_trades} ({pending} en cours)",
        f"✅ Gagnés: {wins} | ❌ Perdus: {losses} | 📈 WR: {wr:.0f}%",
        f"{pnl_emoji} P&L total: *{total_pnl:+.2f} USDC*\n",
    ]

    if subs:
        lines.append("*Abonnements:*")
        for sub, strat in subs:
            lines.append(
                f"  • *{strat.name}* — ${sub.trade_size:.0f}/signal "
                f"(WR: {strat.win_rate:.0f}%)"
            )
    else:
        lines.append("_Aucun abonnement actif._")

    keyboard = [
        [InlineKeyboardButton("📜 Historique trades", callback_data="strat_history")],
        [InlineKeyboardButton("📊 Voir stratégies", callback_data="menu_strategies")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def strat_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show last 20 strategy trades."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await query.edit_message_text("❌ Compte non trouvé.")
            return

        trades = (
            await session.execute(
                select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.strategy_id.isnot(None),
                ).order_by(desc(Trade.created_at)).limit(20)
            )
        ).scalars().all()

    if not trades:
        keyboard = [[InlineKeyboardButton("⬅️ Retour", callback_data="strat_status")]]
        await query.edit_message_text(
            "📜 *Historique trades stratégie*\n\n_Aucun trade._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    lines = ["📜 *DERNIERS TRADES STRATÉGIE*\n━━━━━━━━━━━━━━━━━━━━\n"]

    for trade in trades:
        dt = trade.created_at.strftime("%d/%m %H:%M") if trade.created_at else "?"
        side_emoji = "🟢" if trade.side.value == "buy" else "🔴"
        side_text = trade.side.value.upper()
        status = trade.status.value

        result_str = ""
        if trade.result:
            r_emoji = "✅" if trade.result == "WON" else "❌"
            pnl = trade.pnl or 0
            result_str = f" → {r_emoji} {trade.result} ({pnl:+.2f}$)"

        slug = (trade.market_slug or trade.market_id or "?")[:30]

        lines.append(
            f"{side_emoji} {dt} | {side_text} ${trade.net_amount_usdc:.2f} "
            f"| `{trade.strategy_id}`{result_str}\n"
            f"  _{slug}_"
        )

    keyboard = [
        [InlineKeyboardButton("⬅️ Retour", callback_data="strat_status")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def get_strategy_status_handlers() -> list:
    """Return handlers for strategy status views."""
    return [
        CallbackQueryHandler(strat_status, pattern="^strat_status$"),
        CallbackQueryHandler(strat_history, pattern="^strat_history$"),
    ]
