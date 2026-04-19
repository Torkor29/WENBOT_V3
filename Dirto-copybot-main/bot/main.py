"""Telegram bot entry point – aiogram v3."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from shared.config import TELEGRAM_TOKEN

from bot.handlers import (
    balance,
    deposit,
    export_key,
    history,
    settings,
    start,
    status,
    strategies,
    subscribe,
    unsubscribe,
    withdraw,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _build_dispatcher() -> Dispatcher:
    """Create the Dispatcher and register all routers."""
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(deposit.router)
    dp.include_router(balance.router)
    dp.include_router(strategies.router)
    dp.include_router(subscribe.router)
    dp.include_router(unsubscribe.router)
    dp.include_router(status.router)
    dp.include_router(history.router)
    dp.include_router(withdraw.router)
    dp.include_router(settings.router)
    dp.include_router(export_key.router)
    return dp


async def main() -> None:
    """Start the bot with long-polling."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set")

    bot = Bot(
        token=TELEGRAM_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = _build_dispatcher()

    logger.info("Bot starting …")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
