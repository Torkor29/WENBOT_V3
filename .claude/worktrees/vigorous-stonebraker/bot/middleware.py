"""Telegram handler middleware — rate limiting and security checks."""

import functools
import logging
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.rate_limiter import rate_limiter, LIMITS

logger = logging.getLogger(__name__)


def rate_limited(limit_type: str = "command"):
    """Decorator to apply rate limiting to Telegram handlers.

    Usage:
        @rate_limited("command")
        async def my_handler(update, context):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(
            update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
        ):
            user = update.effective_user
            if not user:
                return await func(update, context, *args, **kwargs)

            max_req, window = LIMITS.get(limit_type, (10, 60))
            key = f"user:{user.id}:{limit_type}"

            result = await rate_limiter.check(key, max_req, window)

            if not result.allowed:
                wait_time = int(result.reset_in_seconds)
                if update.callback_query:
                    await update.callback_query.answer(
                        f"⏳ Trop de requêtes. Réessayez dans {wait_time}s.",
                        show_alert=True,
                    )
                elif update.message:
                    await update.message.reply_text(
                        f"⏳ **Limite atteinte** — {result.limit} actions max "
                        f"par période.\n\nRéessayez dans **{wait_time}s**.",
                        parse_mode="Markdown",
                    )
                logger.warning(
                    f"Rate limited user {user.id} on {limit_type} "
                    f"(remaining: {result.remaining})"
                )
                return

            return await func(update, context, *args, **kwargs)

        return wrapper
    return decorator


def admin_only(func: Callable):
    """Decorator to restrict a handler to admin users only."""
    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ):
        from bot.handlers.admin import is_admin

        user = update.effective_user
        if not user or not is_admin(user.id):
            if update.message:
                await update.message.reply_text("🚫 Accès refusé — admin uniquement.")
            elif update.callback_query:
                await update.callback_query.answer("🚫 Admin uniquement.", show_alert=True)
            return

        return await func(update, context, *args, **kwargs)

    return wrapper
