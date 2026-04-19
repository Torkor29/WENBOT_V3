"""APScheduler tasks — periodic maintenance jobs."""

import logging
from datetime import datetime, timezone

from sqlalchemy import update

from bot.db.session import async_session
from bot.models.user import User
from bot.services.otp import otp_service

logger = logging.getLogger(__name__)


async def reset_daily_limits() -> None:
    """Reset all users' daily spend counters. Runs at midnight UTC."""
    async with async_session() as session:
        await session.execute(
            update(User).values(daily_spent_usdc=0.0)
        )
        await session.commit()

    logger.info("Daily spending limits reset for all users")


async def cleanup_expired_otps() -> None:
    """Remove expired OTP challenges. Runs every 10 minutes."""
    count = otp_service.cleanup_expired()
    if count > 0:
        logger.info(f"Cleaned up {count} expired OTP challenges")


async def health_check() -> None:
    """Periodic health check — verify DB and services. Runs every 5 minutes."""
    try:
        async with async_session() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        logger.debug("Health check: DB OK")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
