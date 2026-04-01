"""PerfFeeService — daily performance fee collection for strategy users.

Ported from Dirto-copybot-main/engine/perf_fee_cron.py.
Runs as an APScheduler job at midnight UTC.
Uses SQLAlchemy async and WENBOT's web3_client.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_

from bot.config import settings
from bot.db.session import async_session
from bot.models.daily_performance_fee import DailyPerformanceFee, PerfFeeStatus
from bot.models.trade import Trade
from bot.models.user import User

logger = logging.getLogger(__name__)


async def collect_daily_perf_fees(bot=None, topic_router=None) -> None:
    """Collect performance fees from all active users based on yesterday's PnL.

    Registered as APScheduler job in scheduler.py (CronTrigger hour=0, minute=0).
    """
    yesterday = date.today() - timedelta(days=1)

    async with async_session() as session:
        # Get all active users who have strategy subscriptions
        users = (
            await session.execute(
                select(User).where(User.is_active == True)  # noqa: E712
            )
        ).scalars().all()

    if not users:
        logger.info("No active users for perf fee collection")
        return

    logger.info(
        "Collecting performance fees for %d users, date=%s",
        len(users), yesterday.isoformat(),
    )

    for user in users:
        try:
            await _process_user_perf_fee(user, yesterday, bot, topic_router)
        except Exception:
            logger.exception("Perf fee error: user=%d", user.id)


async def _process_user_perf_fee(
    user: User,
    fee_date: date,
    bot=None,
    topic_router=None,
) -> None:
    """Process performance fee for a single user."""
    # Query yesterday's resolved strategy trades
    start_of_day = datetime(fee_date.year, fee_date.month, fee_date.day)
    end_of_day = datetime(fee_date.year, fee_date.month, fee_date.day, 23, 59, 59)

    async with async_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.strategy_id.isnot(None),
                Trade.resolved_at.isnot(None),
                Trade.resolved_at >= start_of_day,
                Trade.resolved_at <= end_of_day,
            )
        )
        trades = list(result.scalars().all())

    if not trades:
        return

    total_pnl = sum(t.pnl or 0 for t in trades)
    total_count = len(trades)
    wins = sum(1 for t in trades if t.result == "WON")
    losses = total_count - wins

    perf_fee_rate = settings.strategy_perf_fee_rate

    # If PnL <= 0, skip
    if total_pnl <= 0:
        await _insert_fee_record(
            user.id, fee_date, total_count, wins, losses,
            total_pnl, perf_fee_rate, 0, None, PerfFeeStatus.SKIPPED,
        )
        logger.info("Perf fee SKIPPED: user=%d pnl=%.2f (non-positive)", user.id, total_pnl)
        return

    # Calculate fee
    perf_fee = total_pnl * perf_fee_rate

    # Check strategy wallet balance
    wallet = user.strategy_wallet_address
    if wallet:
        try:
            from bot.services.web3_client import polygon_client
            usdc_balance = await polygon_client.get_usdc_balance(wallet)
            if perf_fee > usdc_balance:
                perf_fee = usdc_balance
        except Exception:
            logger.warning("Balance check failed for perf fee: user=%d", user.id)

    # Skip if too small
    if perf_fee < 0.01:
        await _insert_fee_record(
            user.id, fee_date, total_count, wins, losses,
            total_pnl, perf_fee_rate, perf_fee, None, PerfFeeStatus.SKIPPED,
        )
        logger.info("Perf fee SKIPPED: user=%d fee=%.4f too small", user.id, perf_fee)
        return

    # Send fee transfer
    tx_hash = None
    status = PerfFeeStatus.PENDING

    if settings.collect_fees_onchain and wallet and settings.fees_wallet:
        try:
            from bot.services.crypto import decrypt_private_key
            pk = decrypt_private_key(
                user.encrypted_strategy_private_key,
                settings.encryption_key,
            )

            from bot.services.web3_client import polygon_client
            tx_hash = await polygon_client.transfer_usdc(
                private_key=pk,
                to_address=settings.fees_wallet,
                amount_usdc=perf_fee,
            )
            del pk

            status = PerfFeeStatus.SENT
            logger.info(
                "Perf fee SENT: user=%d pnl=%.2f fee=%.4f tx=%s",
                user.id, total_pnl, perf_fee, tx_hash,
            )
        except Exception:
            logger.exception("Perf fee transfer failed: user=%d", user.id)
            status = PerfFeeStatus.FAILED
    else:
        # Fees not collected on-chain — just record
        status = PerfFeeStatus.SENT
        logger.info(
            "Perf fee recorded (no on-chain): user=%d pnl=%.2f fee=%.4f",
            user.id, total_pnl, perf_fee,
        )

    await _insert_fee_record(
        user.id, fee_date, total_count, wins, losses,
        total_pnl, perf_fee_rate, perf_fee, tx_hash, status,
    )

    # Notify user
    if bot and user.telegram_id:
        await _notify_perf_fee(
            bot, topic_router, user, fee_date,
            total_count, wins, losses, total_pnl, perf_fee,
        )


async def _insert_fee_record(
    user_id, fee_date, total_trades, wins, losses,
    total_pnl, rate, amount, tx_hash, status,
) -> None:
    """Insert a DailyPerformanceFee record."""
    async with async_session() as session:
        record = DailyPerformanceFee(
            user_id=user_id,
            fee_date=fee_date,
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            total_pnl=round(total_pnl, 4),
            perf_fee_rate=rate,
            perf_fee_amount=round(amount, 4),
            perf_fee_tx_hash=tx_hash,
            status=status,
        )
        session.add(record)
        await session.commit()


async def _notify_perf_fee(
    bot, topic_router, user, fee_date,
    total_trades, wins, losses, total_pnl, perf_fee,
) -> None:
    """Send daily performance recap to user."""
    try:
        wr = (wins / total_trades * 100) if total_trades > 0 else 0
        emoji = "🟢" if total_pnl > 0 else "🔴"

        text = (
            f"{emoji} *STRATÉGIE — RECAP QUOTIDIEN*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {fee_date.isoformat()}\n"
            f"📊 Trades : {total_trades} (✅ {wins} / ❌ {losses})\n"
            f"📈 Win Rate : {wr:.0f}%\n"
            f"💰 P&L : *{total_pnl:+.2f} USDC*\n"
            f"💸 Fee perf (5%) : {perf_fee:.4f} USDC"
        )

        from bot.services.topic_router import TopicRouter
        user_router = await TopicRouter.for_user(user.id, bot)
        router = user_router or topic_router

        if router and router.is_enabled:
            await router.send_strategy_perf(text)
        else:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                parse_mode="Markdown",
            )
    except Exception:
        logger.exception("Perf fee notification failed: user=%d", user.id)
