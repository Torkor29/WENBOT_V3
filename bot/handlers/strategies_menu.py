"""Strategy menu handler — list, subscribe, unsubscribe to strategies.

ConversationHandler with FSM states for the subscribe flow.
Callback prefix: strat_ (avoids collision with existing prefixes).
"""

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlalchemy import select

from bot.config import settings
from bot.db.session import async_session
from bot.models.strategy import Strategy, StrategyStatus, StrategyVisibility
from bot.models.subscription import Subscription
from bot.models.strategy_user_settings import StrategyUserSettings
from bot.models.user import User
from bot.services.user_service import get_user_by_telegram_id

logger = logging.getLogger(__name__)

# Conversation states
LIST, SUBSCRIBE_SIZE, SUBSCRIBE_FEE, SUBSCRIBE_CONFIRM = range(4)


# ── List strategies ──────────────────────────────────────────────────

async def strat_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show all active public strategies with subscribe buttons."""
    query = update.callback_query
    if query:
        await query.answer()

    async with async_session() as session:
        strategies = (
            await session.execute(
                select(Strategy).where(
                    Strategy.status == StrategyStatus.ACTIVE,
                    Strategy.visibility == StrategyVisibility.PUBLIC,
                )
            )
        ).scalars().all()

        # Get user's current subscriptions
        tg_user = update.effective_user
        user = await get_user_by_telegram_id(session, tg_user.id)
        user_sub_ids = set()
        if user:
            subs = (
                await session.execute(
                    select(Subscription.strategy_id).where(
                        Subscription.user_id == user.id,
                        Subscription.is_active == True,  # noqa: E712
                    )
                )
            ).scalars().all()
            user_sub_ids = set(subs)

    if not strategies:
        text = (
            "📊 *STRATÉGIES DISPONIBLES*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Aucune stratégie active pour le moment.\n\n"
            "Les stratégies seront ajoutées prochainement."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Menu", callback_data="menu_back")]]
        if query:
            await query.edit_message_text(text, parse_mode="Markdown",
                                         reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, parse_mode="Markdown",
                                           reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    lines = ["📊 *STRATÉGIES DISPONIBLES*\n━━━━━━━━━━━━━━━━━━━━\n"]
    keyboard = []

    for strat in strategies:
        subscribed = "✅" if strat.id in user_sub_ids else ""
        wr = f"{strat.win_rate:.0f}%" if strat.win_rate else "N/A"
        lines.append(
            f"\n*{strat.name}* {subscribed}\n"
            f"  📈 WR: {wr} | 📊 {strat.total_trades} trades | "
            f"💰 PnL: {strat.total_pnl:+.2f}$\n"
            f"  💵 Mise: {strat.min_trade_size}-{strat.max_trade_size}$"
        )
        if strat.description:
            desc_short = strat.description[:60] + ("..." if len(strat.description) > 60 else "")
            lines.append(f"  _{desc_short}_")

        if strat.id in user_sub_ids:
            keyboard.append([InlineKeyboardButton(
                f"❌ Se désabonner de {strat.name}",
                callback_data=f"strat_unsub:{strat.id}",
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                f"➕ S'abonner à {strat.name}",
                callback_data=f"strat_pick:{strat.id}",
            )])

    keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data="menu_back")])

    text = "\n".join(lines)
    if query:
        await query.edit_message_text(text, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(keyboard))
    return LIST


# ── Subscribe flow ───────────────────────────────────────────────────

async def strat_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User picked a strategy — ask for trade size."""
    query = update.callback_query
    await query.answer()

    strategy_id = query.data.split(":")[1]
    context.user_data["strat_sub_id"] = strategy_id

    # Fetch strategy details
    async with async_session() as session:
        strat = await session.get(Strategy, strategy_id)
        if strat:
            context.user_data["strat_sub_name"] = strat.name
            min_size = strat.min_trade_size
            max_size = strat.max_trade_size
        else:
            context.user_data["strat_sub_name"] = strategy_id
            min_size, max_size = 2.0, 10.0

    keyboard = [
        [
            InlineKeyboardButton("$2", callback_data="strat_size:2"),
            InlineKeyboardButton("$4", callback_data="strat_size:4"),
            InlineKeyboardButton("$6", callback_data="strat_size:6"),
        ],
        [InlineKeyboardButton("✏️ Montant personnalisé", callback_data="strat_size:custom")],
        [InlineKeyboardButton("❌ Annuler", callback_data="strat_cancel")],
    ]

    await query.edit_message_text(
        f"💰 *Abonnement à {context.user_data['strat_sub_name']}*\n\n"
        f"Choisissez le montant par signal (${min_size}-${max_size}) :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SUBSCRIBE_SIZE


async def strat_size_picked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle trade size selection."""
    query = update.callback_query
    await query.answer()

    size_str = query.data.split(":")[1]

    if size_str == "custom":
        await query.edit_message_text(
            "✏️ Entrez le montant en USDC (ex: `5.50`) :",
            parse_mode="Markdown",
        )
        return SUBSCRIBE_SIZE  # Wait for text input

    trade_size = float(size_str)
    context.user_data["strat_trade_size"] = trade_size
    return await _ask_fee_rate(query, context)


async def strat_size_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom trade size text input."""
    try:
        size = float(update.message.text.strip().replace("$", ""))
    except ValueError:
        await update.message.reply_text("❌ Montant invalide. Entrez un nombre (ex: `5.50`).")
        return SUBSCRIBE_SIZE

    if size < 1.0 or size > 100.0:
        await update.message.reply_text("❌ Montant entre $1 et $100.")
        return SUBSCRIBE_SIZE

    context.user_data["strat_trade_size"] = size
    return await _ask_fee_rate(update.message, context)


async def _ask_fee_rate(reply_target, context) -> int:
    """Ask for fee rate."""
    keyboard = [
        [
            InlineKeyboardButton("1%", callback_data="strat_fee:0.01"),
            InlineKeyboardButton("2%", callback_data="strat_fee:0.02"),
            InlineKeyboardButton("3%", callback_data="strat_fee:0.03"),
        ],
        [
            InlineKeyboardButton("5%", callback_data="strat_fee:0.05"),
            InlineKeyboardButton("✏️ Autre %", callback_data="strat_fee:custom"),
        ],
        [InlineKeyboardButton("❌ Annuler", callback_data="strat_cancel")],
    ]

    text = (
        "💸 *Taux de fee par trade*\n\n"
        "Fee plus élevé = exécution prioritaire.\n"
        "Minimum: 1% — Maximum: 20%"
    )

    if hasattr(reply_target, 'edit_message_text'):
        await reply_target.edit_message_text(text, parse_mode="Markdown",
                                            reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await reply_target.reply_text(text, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(keyboard))
    return SUBSCRIBE_FEE


async def strat_fee_picked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle fee rate selection."""
    query = update.callback_query
    await query.answer()

    fee_str = query.data.split(":")[1]

    if fee_str == "custom":
        await query.edit_message_text(
            "✏️ Entrez le taux de fee en % (ex: `2.5`) :",
            parse_mode="Markdown",
        )
        return SUBSCRIBE_FEE

    fee_rate = float(fee_str)
    context.user_data["strat_fee_rate"] = fee_rate
    return await _show_confirmation(query, context)


async def strat_fee_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom fee rate text input."""
    try:
        pct = float(update.message.text.strip().replace("%", ""))
    except ValueError:
        await update.message.reply_text("❌ Pourcentage invalide. Entrez un nombre (ex: `2.5`).")
        return SUBSCRIBE_FEE

    if pct < 1.0 or pct > 20.0:
        await update.message.reply_text("❌ Fee entre 1% et 20%.")
        return SUBSCRIBE_FEE

    fee_rate = round(pct / 100, 4)
    context.user_data["strat_fee_rate"] = fee_rate
    return await _show_confirmation(update.message, context)


async def _show_confirmation(reply_target, context) -> int:
    """Show subscription summary and ask for confirmation."""
    name = context.user_data.get("strat_sub_name", "?")
    size = context.user_data.get("strat_trade_size", 4.0)
    fee = context.user_data.get("strat_fee_rate", 0.01)

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmer", callback_data="strat_confirm"),
            InlineKeyboardButton("❌ Annuler", callback_data="strat_cancel"),
        ]
    ]

    text = (
        "📋 *Résumé de l'abonnement*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Stratégie : *{name}*\n"
        f"💰 Mise par signal : *${size:.2f}*\n"
        f"💸 Fee par trade : *{fee*100:.1f}%*\n\n"
        "Confirmer l'abonnement ?"
    )

    if hasattr(reply_target, 'edit_message_text'):
        await reply_target.edit_message_text(text, parse_mode="Markdown",
                                            reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await reply_target.reply_text(text, parse_mode="Markdown",
                                     reply_markup=InlineKeyboardMarkup(keyboard))
    return SUBSCRIBE_CONFIRM


async def strat_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finalize subscription."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user
    strategy_id = context.user_data.get("strat_sub_id")
    trade_size = context.user_data.get("strat_trade_size", 4.0)
    fee_rate = context.user_data.get("strat_fee_rate", 0.01)

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await query.edit_message_text("❌ Compte non trouvé. Lancez /start.")
            return ConversationHandler.END

        # Check if strategy wallet exists
        if not user.strategy_wallet_address:
            keyboard = [
                [InlineKeyboardButton("🆕 Créer un wallet stratégie", callback_data="strat_create_wallet")],
                [InlineKeyboardButton("⬅️ Retour", callback_data="menu_strategies")],
            ]
            await query.edit_message_text(
                "⚠️ *Wallet stratégie requis*\n\n"
                "Vous devez configurer un wallet dédié aux stratégies.\n"
                "Ce wallet est séparé de votre wallet copy-trading.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return ConversationHandler.END

        # Create or update subscription
        existing = (
            await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.strategy_id == strategy_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.trade_size = trade_size
            existing.is_active = True
        else:
            sub = Subscription(
                user_id=user.id,
                strategy_id=strategy_id,
                trade_size=trade_size,
            )
            session.add(sub)

        # Update or create strategy user settings
        sus = (
            await session.execute(
                select(StrategyUserSettings).where(
                    StrategyUserSettings.user_id == user.id
                )
            )
        ).scalar_one_or_none()

        if sus:
            sus.trade_fee_rate = fee_rate
        else:
            sus = StrategyUserSettings(
                user_id=user.id,
                trade_fee_rate=fee_rate,
            )
            session.add(sus)

        await session.commit()

    name = context.user_data.get("strat_sub_name", strategy_id)

    # Clear context
    for key in ("strat_sub_id", "strat_sub_name", "strat_trade_size", "strat_fee_rate"):
        context.user_data.pop(key, None)

    keyboard = [
        [InlineKeyboardButton("📊 Voir mes stratégies", callback_data="menu_strategies")],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await query.edit_message_text(
        f"✅ *Abonné à {name} !*\n\n"
        f"💰 Mise: ${trade_size:.2f} par signal\n"
        f"💸 Fee: {fee_rate*100:.1f}%\n\n"
        f"Les signaux seront exécutés automatiquement sur votre wallet stratégie.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


# ── Unsubscribe ──────────────────────────────────────────────────────

async def strat_unsub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Unsubscribe from a strategy."""
    query = update.callback_query
    await query.answer()

    strategy_id = query.data.split(":")[1]
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await query.edit_message_text("❌ Compte non trouvé.")
            return ConversationHandler.END

        sub = (
            await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.strategy_id == strategy_id,
                )
            )
        ).scalar_one_or_none()

        if sub:
            sub.is_active = False
            await session.commit()

    keyboard = [[InlineKeyboardButton("📊 Retour aux stratégies", callback_data="menu_strategies")]]
    await query.edit_message_text(
        f"❌ Désabonné de `{strategy_id}`.\n\n"
        "Vous ne recevrez plus les signaux de cette stratégie.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


# ── Strategy wallet creation ─────────────────────────────────────────

async def strat_create_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create a dedicated strategy wallet."""
    from web3 import Web3

    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user

    w3 = Web3()
    account = w3.eth.account.create()
    wallet_address = account.address
    private_key = account.key.hex()

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await query.edit_message_text("❌ Compte non trouvé.")
            return ConversationHandler.END

        # Encrypt and save strategy wallet
        from bot.services.crypto import encrypt_private_key
        encrypted = encrypt_private_key(private_key, settings.encryption_key)
        user.strategy_wallet_address = wallet_address
        user.encrypted_strategy_private_key = encrypted
        user.strategy_wallet_auto_created = True
        await session.commit()

    del private_key

    keyboard = [
        [InlineKeyboardButton("📊 Voir les stratégies", callback_data="menu_strategies")],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]
    await query.edit_message_text(
        "🎉 *Wallet stratégie créé !*\n\n"
        f"📬 Adresse :\n`{wallet_address}`\n\n"
        "🔒 Clé privée chiffrée AES-256-GCM ✅\n\n"
        "Ce wallet est **séparé** de votre wallet copy-trading.\n"
        "Déposez des USDC dessus pour commencer le suivi de stratégies.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


# ── Cancel ───────────────────────────────────────────────────────────

async def strat_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel subscription flow."""
    query = update.callback_query
    await query.answer()

    for key in ("strat_sub_id", "strat_sub_name", "strat_trade_size", "strat_fee_rate"):
        context.user_data.pop(key, None)

    keyboard = [[InlineKeyboardButton("📊 Stratégies", callback_data="menu_strategies")],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu_back")]]
    await query.edit_message_text(
        "❌ Annulé.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


# ── Handler factory ──────────────────────────────────────────────────

def get_strategies_menu_handler() -> ConversationHandler:
    """Build the strategies ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(strat_list, pattern="^menu_strategies$"),
            CallbackQueryHandler(strat_pick, pattern=r"^strat_pick:"),
        ],
        states={
            LIST: [
                CallbackQueryHandler(strat_pick, pattern=r"^strat_pick:"),
                CallbackQueryHandler(strat_unsub, pattern=r"^strat_unsub:"),
            ],
            SUBSCRIBE_SIZE: [
                CallbackQueryHandler(strat_size_picked, pattern=r"^strat_size:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, strat_size_text),
            ],
            SUBSCRIBE_FEE: [
                CallbackQueryHandler(strat_fee_picked, pattern=r"^strat_fee:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, strat_fee_text),
            ],
            SUBSCRIBE_CONFIRM: [
                CallbackQueryHandler(strat_confirm, pattern="^strat_confirm$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(strat_cancel, pattern="^strat_cancel$"),
            CallbackQueryHandler(strat_list, pattern="^menu_strategies$"),
        ],
        per_user=True,
        per_message=False,
    )


def get_strategy_wallet_handler():
    """Standalone handler for strategy wallet creation."""
    return CallbackQueryHandler(strat_create_wallet, pattern="^strat_create_wallet$")
