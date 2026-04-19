"""Main menu callback handlers — each button directly executes the relevant logic."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ContextTypes
from sqlalchemy import select, func

from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id, get_or_create_settings, switch_wallet
from bot.services.web3_client import polygon_client

logger = logging.getLogger(__name__)


def _build_main_menu_content(tg_user, user) -> tuple[str, list]:
    """Build main menu text and keyboard (single source of truth)."""
    if user.is_active and not user.is_paused:
        status = "🟢 Actif"
    elif user.is_paused:
        status = "🟡 Pause"
    else:
        status = "🔴 Inactif"

    mode = "📝 Paper" if user.paper_trading else "💵 Réel"
    wallet_short = (
        f"`{user.wallet_address[:6]}...{user.wallet_address[-4:]}`"
        if user.wallet_address
        else "Non configuré"
    )
    us = user.settings
    traders_count = len(us.followed_wallets) if us and us.followed_wallets else 0

    text = (
        f"**WENPOLYMARKET** — Copy-Trading Polymarket\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Bonjour **{tg_user.first_name}** !\n\n"
        f"📬 Wallet : {wallet_short}\n"
        f"🎛️ {status} • {mode}\n"
        f"👥 {traders_count} trader(s) suivi(s)\n"
    )

    if not user.wallet_address:
        text += (
            "\n⚠️ **Wallet non configuré** — Cliquez sur "
            "« 🧭 Configurer mon wallet » pour commencer.\n"
        )

    keyboard = []
    if not user.wallet_address:
        keyboard.append(
            [InlineKeyboardButton(
                "🧭 Configurer mon wallet", callback_data="onboard_start"
            )]
        )

    keyboard.extend([
        [
            InlineKeyboardButton("👛 Wallets", callback_data="menu_balance"),
            InlineKeyboardButton("📊 Positions", callback_data="menu_positions"),
        ],
        [
            InlineKeyboardButton("💸 Retirer", callback_data="menu_withdraw"),
            InlineKeyboardButton("📜 Historique", callback_data="menu_history"),
        ],
        [
            InlineKeyboardButton("👥 Traders suivis", callback_data="menu_traders"),
            InlineKeyboardButton("⚙️ Paramètres", callback_data="menu_settings"),
        ],
        [InlineKeyboardButton("❓ Aide", callback_data="menu_help")],
    ])

    return text, keyboard


async def _send_main_menu(message, tg_user, text_override: str | None = None) -> None:
    """Build and send the main menu (reusable)."""
    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await message.reply_text(
                "❌ Compte non trouvé. Lancez /start pour vous inscrire."
            )
            return

        text, keyboard = _build_main_menu_content(tg_user, user)

    header = text_override or text

    await message.reply_text(
        header, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── Balance ──────────────────────────────────────────

async def menu_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, query.from_user.id)
        if not user:
            return

        polygon_wallets = [w for w in (user.wallets or []) if w.chain == "polygon"]
        primary_address = user.wallet_address or ""

    header = "👛 **WALLETS**\n━━━━━━━━━━━━━━━━━━━━\n\n"

    if not polygon_wallets and not primary_address:
        text = (
            header
            + "Aucun wallet configuré.\n"
            "👉 Utilisez « 🧭 Configurer mon wallet » pour créer ou importer un wallet.\n"
        )
        keyboard = [
            [InlineKeyboardButton("🧭 Configurer mon wallet", callback_data="onboard_start")],
            [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
        ]
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Build wallet list with balances for the primary wallet
    blocks: list[str] = []
    keyboard: list[list[InlineKeyboardButton]] = []

    for w in polygon_wallets:
        is_active = w.address == primary_address and w.is_primary
        label = w.label or f"Wallet {w.id}"
        short = f"`{w.address[:6]}...{w.address[-4:]}`"
        origin = "bot" if w.auto_created else "importé"

        if is_active:
            # Fetch balances only for the active wallet
            usdc_native, usdc_e = await polygon_client.get_usdc_balances(w.address)
            pol = await polygon_client.get_matic_balance(w.address)
            blocks.append(
                f"🟢 **{label}** — _actif (copy-trading)_\n"
                f"   📬 {short} ({origin})\n"
                f"   💵 USDC : **{usdc_native:.2f}** | USDC.e : **{usdc_e:.2f}**\n"
                f"   ⛽ POL : **{pol:.4f}**\n"
            )
            if usdc_e > 0 and usdc_native == 0:
                blocks.append(
                    "   ⚠️ _Swappez vos USDC.e en USDC natif pour trader._\n"
                )
        else:
            blocks.append(
                f"⚪ **{label}** — _inactif_\n"
                f"   📬 {short} ({origin})\n"
            )
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 Activer « {label} »",
                    callback_data=f"wallet_switch_{w.id}",
                )
            ])

    text = header + "\n".join(blocks)

    keyboard.extend([
        [
            InlineKeyboardButton("💳 Déposer", callback_data="menu_deposit"),
            InlineKeyboardButton("💸 Retirer", callback_data="menu_withdraw"),
        ],
        [InlineKeyboardButton("🧭 Ajouter un wallet", callback_data="onboard_start")],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ])

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── Wallet switch ────────────────────────────────────

async def wallet_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch the active wallet used for copy-trading."""
    query = update.callback_query
    await query.answer()

    wallet_id_str = query.data.replace("wallet_switch_", "")
    try:
        wallet_id = int(wallet_id_str)
    except ValueError:
        await query.edit_message_text("❌ Wallet invalide.")
        return

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, query.from_user.id)
        if not user:
            return

        ok = await switch_wallet(session, user, wallet_id)
        if not ok:
            await query.edit_message_text(
                "❌ Wallet introuvable ou inaccessible."
            )
            return

        # Find the wallet label for confirmation
        label = ""
        for w in user.wallets:
            if w.id == wallet_id:
                label = w.label or f"Wallet {w.id}"
                break

    # Re-render the wallets screen with the new active wallet
    # We call menu_balance logic by simulating the same flow
    await menu_balance(update, context)


# ── Positions ────────────────────────────────────────

async def menu_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, query.from_user.id)
        if not user:
            return

        from bot.models.trade import Trade, TradeStatus
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id, Trade.status == TradeStatus.FILLED
            ).order_by(Trade.created_at.desc()).limit(15)
        )
        trades = result.scalars().all()

    if not trades:
        text = "📊 **Positions actives**\n\nAucune position pour le moment."
    else:
        lines = ["📊 **POSITIONS ACTIVES**\n━━━━━━━━━━━━━━━━━━━━\n"]
        for t in trades:
            emoji = "🟢" if t.side.value == "buy" else "🔴"
            q = t.market_question or t.market_id
            if len(q) > 40:
                q = q[:37] + "..."
            lines.append(
                f"{emoji} **{q}**\n"
                f"   {t.side.value.upper()} @ {t.price:.2f} | "
                f"{t.net_amount_usdc:.2f} USDC\n"
            )
        text = "\n".join(lines)

    keyboard = [[InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")]]
    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── History ──────────────────────────────────────────

async def menu_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, query.from_user.id)
        if not user:
            return

        from bot.models.trade import Trade, TradeStatus
        result = await session.execute(
            select(Trade).where(Trade.user_id == user.id)
            .order_by(Trade.created_at.desc()).limit(15)
        )
        trades = result.scalars().all()

    if not trades:
        text = "📜 **Historique**\n\nAucun trade enregistré."
    else:
        status_emoji = {"filled": "✅", "failed": "❌", "cancelled": "🚫", "pending": "🟡", "executing": "🔄"}
        lines = ["📜 **HISTORIQUE**\n━━━━━━━━━━━━━━━━━━━━\n"]
        for t in trades:
            emoji = status_emoji.get(t.status.value, "❓")
            q = t.market_question or t.market_id
            if len(q) > 35:
                q = q[:32] + "..."
            date_str = t.created_at.strftime("%d/%m %H:%M") if t.created_at else "?"
            paper = " 📝" if t.is_paper else ""
            lines.append(f"{emoji} {date_str} | {t.net_amount_usdc:.2f} USDC{paper}\n   {q}\n")
        text = "\n".join(lines)

    keyboard = [[InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")]]
    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── Deposit (inline summary + link to /deposit) ─────

async def menu_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, query.from_user.id)
        wallet = user.wallet_address if user else ""
        auto = user.wallet_auto_created if user else False

    if auto:
        tag = "🏷️ *Wallet créé par le bot — il est vide au départ*"
    else:
        tag = "🏷️ *Wallet importé — vos fonds existants sont utilisables*"

    text = (
        "💳 **DÉPOSER DES USDC**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{tag}\n"
        f"📬 `{wallet}`\n\n"
        "Choisissez une option :"
    )

    keyboard = [
        [InlineKeyboardButton("💳 Carte bancaire", callback_data="dep_card")],
        [InlineKeyboardButton("🏦 Depuis un exchange", callback_data="dep_exchange")],
        [InlineKeyboardButton("🌉 Bridge (SOL, ETH…)", callback_data="dep_bridge")],
        [InlineKeyboardButton("📋 Copier adresse", callback_data="deposit_copy_address")],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── Withdraw / Bridge / Settings / Traders ──────────────────────────

async def menu_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ce handler reste déclaré mais l'action réelle est gérée par
    la ConversationHandler de /withdraw, qui intercepte directement
    le callback « menu_withdraw ». Rien à faire ici."""
    query = update.callback_query
    await query.answer()
    # Le flux de retrait démarre automatiquement via get_withdraw_handler().


async def menu_bridge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Délègue directement au flux /bridge pour éviter de demander une commande."""
    # On laisse la logique d'affichage centralisée dans bridge_command
    from bot.handlers.bridge import bridge_command

    await bridge_command(update, context)


async def menu_traders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, query.from_user.id)
        if not user:
            return
        us = await get_or_create_settings(session, user)
        wallets = us.followed_wallets or []

    if wallets:
        lines = [f"  {i}. `{w[:6]}...{w[-4:]}`" for i, w in enumerate(wallets, 1)]
        wallet_text = "\n".join(lines)
    else:
        wallet_text = "  _Aucun trader suivi_"

    text = (
        "👥 **TRADERS SUIVIS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{wallet_text}\n\n"
        "Pour ajouter ou retirer des traders, utilisez le bouton "
        "**⚙️ Paramètres** ci-dessous."
    )

    keyboard = [
        [InlineKeyboardButton("⚙️ Ouvrir paramètres", callback_data="menu_settings")],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")],
    ]

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def menu_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ce handler est conservé pour compatibilité mais la vraie ouverture
    des paramètres est gérée par la ConversationHandler /settings
    (qui intercepte directement le callback « menu_settings »)."""
    query = update.callback_query
    await query.answer()


async def menu_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    text = (
        "❓ **AIDE — WENPOLYMARKET**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Depuis le menu principal :**\n\n"
        "👛 **Wallets** — Voir vos soldes (USDC, POL)\n"
        "📊 **Positions** — Trades copiés en cours\n"
        "💳 **Déposer** — Carte, exchange, bridge\n"
        "💸 **Retirer** — Envoyer vos USDC ailleurs\n"
        "📜 **Historique** — Derniers trades\n"
        "👥 **Traders suivis** — Wallets copiés\n"
        "⚙️ **Paramètres** — Capital, sizing, risques, traders\n\n"
        "**Comment ça marche :**\n"
        "1. Configurez un wallet Polygon\n"
        "2. Déposez des USDC dessus\n"
        "3. Choisissez vos traders dans Paramètres\n"
        "4. Les trades sont copiés automatiquement\n"
        "5. Frais : 1% par trade copié\n\n"
        "🔒 Clés chiffrées AES-256 • Jamais exposées en clair\n"
        "📝 Paper Trading activé par défaut (sans fonds réels)"
    )

    keyboard = [[InlineKeyboardButton("🏠 Menu principal", callback_data="menu_back")]]
    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ── Back to main menu ───────────────────────────────

async def menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tg_user = query.from_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            return

        text, keyboard = _build_main_menu_content(tg_user, user)

    await query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
    )


def get_menu_handlers() -> list:
    return [
        CallbackQueryHandler(menu_balance, pattern="^menu_balance$"),
        CallbackQueryHandler(wallet_switch, pattern=r"^wallet_switch_\d+$"),
        CallbackQueryHandler(menu_positions, pattern="^menu_positions$"),
        # menu_deposit conservé pour compat, mais plus utilisé par le menu principal
        CallbackQueryHandler(menu_deposit, pattern="^menu_deposit$"),
        CallbackQueryHandler(menu_withdraw, pattern="^menu_withdraw$"),
        CallbackQueryHandler(menu_traders, pattern="^menu_traders$"),
        CallbackQueryHandler(menu_settings, pattern="^menu_settings$"),
        CallbackQueryHandler(menu_bridge, pattern="^menu_bridge$"),
        CallbackQueryHandler(menu_history, pattern="^menu_history$"),
        CallbackQueryHandler(menu_help, pattern="^menu_help$"),
        CallbackQueryHandler(menu_back, pattern="^menu_back$"),
    ]
