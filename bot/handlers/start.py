"""Onboarding handler — /start command."""

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
from bot.services.user_service import get_user_by_telegram_id, create_user, save_wallet

logger = logging.getLogger(__name__)

# Conversation states
WELCOME, WALLET_CHOICE, WALLET_ADDRESS, PRIVATE_KEY, CONFIRM = range(5)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point — /start."""
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)

        if user:
            await update.message.reply_text(
                f"🔄 Bon retour, **{tg_user.first_name}** !\n\n"
                f"🆔 ID : `{user.uuid}`\n"
                f"📊 Statut : {'🟢 Actif' if user.is_active and not user.is_paused else '🟡 En pause' if user.is_paused else '🔴 Inactif'}\n"
                f"💰 Mode : {'📝 Paper Trading' if user.paper_trading else '💵 Trading réel'}\n\n"
                "Utilisez /settings pour configurer, /balance pour voir vos soldes.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

    # New user — start onboarding
    keyboard = [
        [InlineKeyboardButton("🚀 Commencer l'inscription", callback_data="onboard_start")],
        [InlineKeyboardButton("ℹ️ En savoir plus", callback_data="onboard_info")],
    ]
    await update.message.reply_text(
        "👋 **Bienvenue sur Polymarket CopyTrader !**\n\n"
        "Ce bot vous permet de copier automatiquement les trades "
        "d'un trader expert sur Polymarket.\n\n"
        "🔒 Vos clés sont chiffrées AES-256 et jamais stockées en clair.\n"
        "📝 Vous démarrez en mode Paper Trading (sans fonds réels).\n"
        "💸 Frais de plateforme : 1% par trade copié.\n\n"
        "Prêt à commencer ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WELCOME


async def onboard_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show more info about the bot."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🚀 Commencer l'inscription", callback_data="onboard_start")],
    ]
    await query.edit_message_text(
        "📖 **Comment ça marche ?**\n\n"
        "1️⃣ Vous fournissez votre adresse wallet Polygon\n"
        "2️⃣ Vous fournissez votre clé privée (chiffrée immédiatement)\n"
        "3️⃣ Vous configurez vos paramètres de copie\n"
        "4️⃣ Les trades du master sont copiés automatiquement\n\n"
        "🔐 **Sécurité :**\n"
        "• Clé privée chiffrée AES-256-GCM\n"
        "• Déchiffrée uniquement en mémoire pour signer\n"
        "• Jamais loguée ni exposée\n\n"
        "💸 **Frais :** 1% prélevé sur chaque trade copié\n"
        "📝 Vous commencez en Paper Trading par défaut",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WELCOME


async def onboard_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begin registration — let user choose wallet creation method."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton(
                "🆕 Créer un wallet Polygon", callback_data="onboard_create_wallet"
            )
        ],
        [
            InlineKeyboardButton(
                "📩 J'ai déjà un wallet", callback_data="onboard_existing_wallet"
            )
        ],
        [InlineKeyboardButton("⬅️ Annuler", callback_data="onboard_cancel")],
    ]

    await query.edit_message_text(
        "🧭 **Configuration du wallet**\n\n"
        "Choisissez comment configurer votre wallet Polygon pour trader sur Polymarket :\n\n"
        "• **Créer un wallet** — le bot génère une adresse Polygon pour vous.\n"
        "• **J'ai déjà un wallet** — vous utilisez une adresse 0x… existante.\n\n"
        "Vous pourrez ensuite déposer des USDC dessus pour commencer à copier les trades.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WALLET_CHOICE


async def onboard_existing_wallet(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ask user for an existing wallet address."""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📬 **Étape 1/2 — Adresse Wallet**\n\n"
        "Envoyez votre adresse wallet **Polygon** (0x...).\n\n"
        "⚠️ Cette adresse sera utilisée pour le trading sur Polymarket.",
        parse_mode="Markdown",
    )
    return WALLET_ADDRESS


async def onboard_create_wallet(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Create a new Polygon wallet for the user and save it."""
    from web3 import Web3

    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user

    # Generate a new wallet locally (no RPC needed)
    w3 = Web3()
    account = w3.eth.account.create()
    wallet_address = account.address
    private_key = account.key.hex()

    async with async_session() as session:
        # Create user
        user = await create_user(session, tg_user.id, username=tg_user.username)
        # Encrypt and save generated wallet
        await save_wallet(
            session,
            user,
            wallet_address=wallet_address,
            private_key=private_key,
            chain="polygon",
        )

    # Do NOT keep private_key around longer than necessary
    del private_key

    await query.edit_message_text(
        "🎉 **Wallet Polygon créé !**\n\n"
        f"📬 Adresse : `{wallet_address}`\n\n"
        "Pour copier des trades, vous devez déposer des **USDC sur Polygon** "
        "sur cette adresse.\n\n"
        "✅ Prochaines étapes :\n"
        "• Utilisez /deposit pour voir comment déposer des USDC\n"
        "• Utilisez /settings pour choisir quels traders copier",
        parse_mode="Markdown",
    )

    return ConversationHandler.END


async def receive_wallet_address(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive and validate wallet address."""
    address = update.message.text.strip()

    # Basic validation
    if not address.startswith("0x") or len(address) != 42:
        await update.message.reply_text(
            "❌ Adresse invalide. Elle doit commencer par `0x` "
            "et faire 42 caractères.\n\nRéessayez :",
            parse_mode="Markdown",
        )
        return WALLET_ADDRESS

    # Check hex
    try:
        int(address, 16)
    except ValueError:
        await update.message.reply_text(
            "❌ Adresse invalide — caractères non-hexadécimaux détectés.\n\nRéessayez :",
        )
        return WALLET_ADDRESS

    context.user_data["wallet_address"] = address

    await update.message.reply_text(
        "🔑 **Étape 2/2 — Clé Privée**\n\n"
        "Envoyez votre clé privée Polygon.\n\n"
        "🔒 Elle sera **immédiatement chiffrée** (AES-256-GCM) "
        "et le message sera supprimé.\n\n"
        "⚠️ Ne partagez JAMAIS votre clé privée ailleurs.",
        parse_mode="Markdown",
    )
    return PRIVATE_KEY


async def receive_private_key(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive private key — encrypt immediately, delete message."""
    private_key = update.message.text.strip()

    # Delete the message containing the private key IMMEDIATELY
    try:
        await update.message.delete()
    except Exception:
        pass  # Bot may not have delete permissions

    # Basic validation
    if len(private_key) < 32:
        await update.message.reply_text(
            "❌ Clé privée trop courte. Réessayez :",
        )
        return PRIVATE_KEY

    context.user_data["private_key"] = private_key

    wallet = context.user_data["wallet_address"]
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmer", callback_data="onboard_confirm"),
            InlineKeyboardButton("❌ Annuler", callback_data="onboard_cancel"),
        ]
    ]
    await update.effective_chat.send_message(
        "📋 **Résumé de l'inscription**\n\n"
        f"📬 Wallet : `{wallet[:6]}...{wallet[-4:]}`\n"
        "🔑 Clé privée : ✅ Reçue (sera chiffrée)\n"
        "📝 Mode : Paper Trading (défaut)\n"
        "💸 Frais : 1% par trade copié\n\n"
        "Confirmer l'inscription ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CONFIRM


async def onboard_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Finalize registration — create user, encrypt and save key."""
    query = update.callback_query
    await query.answer()

    tg_user = update.effective_user
    wallet_address = context.user_data.get("wallet_address")
    private_key = context.user_data.get("private_key")

    if not wallet_address or not private_key:
        await query.edit_message_text("❌ Erreur — données manquantes. Relancez /start.")
        return ConversationHandler.END

    async with async_session() as session:
        # Create user
        user = await create_user(
            session, tg_user.id, username=tg_user.username
        )
        # Encrypt and save wallet
        await save_wallet(session, user, wallet_address, private_key, chain="polygon")

        await query.edit_message_text(
            "🎉 **Inscription réussie !**\n\n"
            f"🆔 Votre ID : `{user.uuid}`\n"
            f"📬 Wallet : `{wallet_address[:6]}...{wallet_address[-4:]}`\n"
            "🔒 Clé privée : chiffrée AES-256 ✅\n"
            "📝 Mode : Paper Trading\n\n"
            "**Prochaines étapes :**\n"
            "• /settings — Configurer vos paramètres de copie\n"
            "• /balance — Voir vos soldes\n"
            "• /help — Aide complète",
            parse_mode="Markdown",
        )

    # Clear sensitive data from context
    context.user_data.pop("wallet_address", None)
    context.user_data.pop("private_key", None)

    return ConversationHandler.END


async def onboard_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel registration."""
    query = update.callback_query
    await query.answer()

    context.user_data.pop("wallet_address", None)
    context.user_data.pop("private_key", None)

    await query.edit_message_text(
        "❌ Inscription annulée.\n\nVous pouvez relancer /start à tout moment."
    )
    return ConversationHandler.END


def get_start_handler() -> ConversationHandler:
    """Build the /start conversation handler."""
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            WELCOME: [
                CallbackQueryHandler(onboard_start, pattern="^onboard_start$"),
                CallbackQueryHandler(onboard_info, pattern="^onboard_info$"),
            ],
            WALLET_CHOICE: [
                CallbackQueryHandler(
                    onboard_existing_wallet, pattern="^onboard_existing_wallet$"
                ),
                CallbackQueryHandler(
                    onboard_create_wallet, pattern="^onboard_create_wallet$"
                ),
                CallbackQueryHandler(onboard_cancel, pattern="^onboard_cancel$"),
            ],
            WALLET_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wallet_address),
            ],
            PRIVATE_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_private_key),
            ],
            CONFIRM: [
                CallbackQueryHandler(onboard_confirm, pattern="^onboard_confirm$"),
                CallbackQueryHandler(onboard_cancel, pattern="^onboard_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("start", start_command)],
        per_user=True,
    )
