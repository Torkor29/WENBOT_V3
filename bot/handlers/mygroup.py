"""/mygroup command — show user's linked group status and setup instructions.

Works in both DM and group context.
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

from bot.db.session import async_session
from bot.services.user_service import get_user_by_telegram_id

logger = logging.getLogger(__name__)


async def mygroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's linked group status + setup instructions."""
    tg_user = update.effective_user

    async with async_session() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if not user:
            await update.effective_message.reply_text(
                "❌ Vous n'avez pas encore de compte.\nEnvoyez /start en message privé."
            )
            return

        # Look up their group config
        from bot.models.group_config import GroupConfig
        from sqlalchemy import select

        config = (
            await session.execute(
                select(GroupConfig).where(
                    GroupConfig.user_id == user.id,
                    GroupConfig.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()

    if config and config.setup_complete:
        topics = config.topics_dict
        topic_lines = "\n".join(
            f"  {'✅' if tid else '❌'} {name.capitalize()}"
            for name, tid in topics.items()
        )
        keyboard = [
            [InlineKeyboardButton(
                "🔄 Reconfigurer le groupe", callback_data="mygroup_reconfigure"
            )],
        ]
        await update.effective_message.reply_text(
            f"✅ *Votre groupe est configuré !*\n\n"
            f"📊 Groupe : *{config.group_title or 'Inconnu'}*\n"
            f"🆔 ID : `{config.group_id}`\n\n"
            f"*Topics :*\n{topic_lines}\n\n"
            "_Toutes vos notifications (signaux, alerts, portfolio) "
            "sont envoyées dans ce groupe._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    elif config and not config.setup_complete:
        await update.effective_message.reply_text(
            "⚠️ *Groupe lié mais setup incomplet.*\n\n"
            f"Groupe : {config.group_title or config.group_id}\n"
            f"Topics créés : {sum(1 for v in config.topics_dict.values() if v)}/5\n\n"
            "Retirez le bot du groupe et re-ajoutez-le comme admin "
            "pour relancer l'auto-setup.",
            parse_mode="Markdown",
        )
    else:
        bot_username = (await context.bot.get_me()).username or "WenPolymarketBot"
        keyboard = [
            [InlineKeyboardButton(
                "📖 Voir les instructions", callback_data="setup_my_group"
            )],
        ]
        await update.effective_message.reply_text(
            "📊 *Aucun groupe lié*\n\n"
            "Créez votre groupe Telegram personnel pour recevoir "
            "vos notifications organisées en 5 topics.\n\n"
            f"👉 Ajoutez @{bot_username} comme admin dans un groupe "
            "Forum pour démarrer l'auto-setup.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def mygroup_reconfigure_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Ask user to confirm group reconfiguration."""
    query = update.callback_query
    await query.answer()

    bot_username = (await context.bot.get_me()).username or "WenPolymarketBot"
    keyboard = [
        [InlineKeyboardButton("📖 Instructions", callback_data="setup_my_group")],
        [InlineKeyboardButton("⬅️ Retour", callback_data="mygroup_status")],
    ]
    await query.edit_message_text(
        "🔄 *Reconfigurer votre groupe*\n\n"
        "Pour lier un nouveau groupe :\n\n"
        "1. Retirez le bot de l'ancien groupe\n"
        f"2. Ajoutez @{bot_username} dans votre nouveau groupe Forum\n"
        "3. Donnez-lui les droits admin (Gérer les topics)\n\n"
        "Le bot détectera automatiquement le changement.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def mygroup_status_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Refresh group status."""
    query = update.callback_query
    await query.answer()
    # Simulate /mygroup by sending a new message
    await mygroup_command(update, context)


def get_mygroup_handlers() -> list:
    """Return /mygroup command and related callbacks."""
    return [
        CommandHandler("mygroup", mygroup_command),
        CallbackQueryHandler(mygroup_reconfigure_callback, pattern="^mygroup_reconfigure$"),
        CallbackQueryHandler(mygroup_status_callback, pattern="^mygroup_status$"),
    ]
