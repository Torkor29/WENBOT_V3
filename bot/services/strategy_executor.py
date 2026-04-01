"""StrategyExecutor — executes strategy signals for all subscribers.

Ported from Dirto-copybot-main/engine/fee_queue.py + engine/executor.py.
Adapted to use SQLAlchemy async, WENBOT's web3_client & polymarket_client,
and the TopicRouter for notifications.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select

from bot.config import settings
from bot.db.session import async_session
from bot.models.strategy import Strategy
from bot.models.subscription import Subscription
from bot.models.strategy_user_settings import StrategyUserSettings
from bot.models.trade import Trade, TradeStatus, TradeSide
from bot.models.user import User
from bot.services.strategy_listener import StrategySignalData

logger = logging.getLogger(__name__)


class StrategyExecutor:
    """Executes strategy signals for all subscribers, sorted by fee_rate DESC."""

    def __init__(self, bot, topic_router, gas_manager, polymarket_client, web3_client):
        self._bot = bot
        self._topic_router = topic_router
        self._gas_manager = gas_manager
        self._poly = polymarket_client
        self._web3 = web3_client

    async def handle_signal(self, signal: StrategySignalData) -> None:
        """Process a signal: fetch subscribers, sort by fee, execute sequentially."""
        async with async_session() as session:
            # Fetch active subscriptions
            subs = (
                await session.execute(
                    select(Subscription)
                    .where(
                        Subscription.strategy_id == signal.strategy_id,
                        Subscription.is_active == True,  # noqa: E712
                    )
                )
            ).scalars().all()

            if not subs:
                logger.info("No subscribers for strategy=%s", signal.strategy_id)
                return

            # Fetch strategy for execution_delay_ms
            strategy = await session.get(Strategy, signal.strategy_id)
            delay_ms = strategy.execution_delay_ms if strategy else 100

            # Load users + their strategy settings
            user_ids = [s.user_id for s in subs]
            users = (
                await session.execute(
                    select(User).where(User.id.in_(user_ids))
                )
            ).scalars().all()
            users_by_id = {u.id: u for u in users}

            # Load strategy user settings
            all_sus = (
                await session.execute(
                    select(StrategyUserSettings).where(
                        StrategyUserSettings.user_id.in_(user_ids)
                    )
                )
            ).scalars().all()
            sus_by_user = {s.user_id: s for s in all_sus}

        # Sort subscribers by fee_rate DESC (higher fee = higher priority)
        def _fee_rate(sub: Subscription) -> float:
            sus = sus_by_user.get(sub.user_id)
            return sus.trade_fee_rate if sus else 0.01

        sorted_subs = sorted(subs, key=_fee_rate, reverse=True)

        logger.info(
            "Executing signal for %d subscribers: strategy=%s action=%s",
            len(sorted_subs), signal.strategy_id, signal.action,
        )

        # Execute sequentially with delay
        executed = 0
        skipped = 0
        for priority, sub in enumerate(sorted_subs):
            user = users_by_id.get(sub.user_id)
            if not user:
                skipped += 1
                continue

            sus = sus_by_user.get(sub.user_id)
            success = await self._execute_single(
                signal=signal,
                user=user,
                sus=sus,
                trade_size=sub.trade_size,
                priority=priority,
            )

            if success:
                executed += 1
            else:
                skipped += 1

            # Delay between subscribers
            if delay_ms > 0 and priority < len(sorted_subs) - 1:
                await asyncio.sleep(delay_ms / 1000.0)

        # Update signal audit record with execution stats
        await self._update_signal_stats(signal, executed, skipped, sorted_subs)

        logger.info(
            "Signal complete: strategy=%s executed=%d skipped=%d",
            signal.strategy_id, executed, skipped,
        )

    async def _execute_single(
        self,
        signal: StrategySignalData,
        user: User,
        sus: Optional[StrategyUserSettings],
        trade_size: float,
        priority: int,
    ) -> bool:
        """Execute a signal for a single subscriber. Returns True on success."""
        today = date.today()

        # Auto-create strategy settings if missing
        if not sus:
            async with async_session() as session:
                sus = StrategyUserSettings(user_id=user.id)
                session.add(sus)
                await session.commit()
                await session.refresh(sus)

        # Check if paused
        if sus.is_paused:
            logger.info("User paused (strategy): user=%d", user.id)
            return False

        # Reset daily counter if needed
        if sus.trades_today_reset_date != today:
            async with async_session() as session:
                sus_db = await session.get(StrategyUserSettings, sus.id)
                sus_db.trades_today = 0
                sus_db.trades_today_reset_date = today
                await session.commit()
                sus.trades_today = 0

        # CHECK: Daily trade limit
        if sus.trades_today >= sus.max_trades_per_day:
            logger.info(
                "Daily limit reached: user=%d trades=%d/%d",
                user.id, sus.trades_today, sus.max_trades_per_day,
            )
            return False

        # Use strategy wallet
        wallet = user.strategy_wallet_address
        pk_encrypted = user.encrypted_strategy_private_key
        if not wallet or not pk_encrypted:
            logger.info("No strategy wallet for user=%d, skipping", user.id)
            return False

        # CHECK: USDC balance (BUY only)
        if signal.action == "BUY":
            try:
                usdc_balance = await self._web3.get_usdc_balance(wallet)
            except Exception:
                logger.exception("Balance check failed: user=%d", user.id)
                return False

            if usdc_balance < trade_size:
                logger.info(
                    "Insufficient USDC: user=%d balance=%.2f required=%.2f",
                    user.id, usdc_balance, trade_size,
                )
                return False

        # CHECK: MATIC gas
        matic_ok = await self._gas_manager.check_and_refill(user)
        if not matic_ok:
            logger.warning("MATIC check failed: user=%d", user.id)

        # Decrypt private key
        from bot.services.crypto import decrypt_private_key
        try:
            private_key = decrypt_private_key(pk_encrypted, settings.encryption_key)
        except Exception:
            logger.exception("Failed to decrypt strategy key: user=%d", user.id)
            return False

        # Execute trade
        trade_id = str(uuid.uuid4())[:16]
        try:
            if signal.action == "BUY":
                success = await self._execute_buy(
                    user, signal, sus, trade_size, priority, private_key, trade_id
                )
            elif signal.action == "SELL":
                success = await self._execute_sell(
                    user, signal, sus, trade_size, priority, private_key, trade_id
                )
            else:
                logger.warning("Unknown action=%s", signal.action)
                return False
        finally:
            # Clear private key from memory
            del private_key

        # Increment daily counter
        if success:
            async with async_session() as session:
                sus_db = await session.get(StrategyUserSettings, sus.id)
                sus_db.trades_today += 1
                await session.commit()

        return success

    async def _execute_buy(
        self, user, signal, sus, trade_size, priority, private_key, trade_id,
    ) -> bool:
        """BUY: fee transfer + Polymarket order."""
        fee_rate = max(sus.trade_fee_rate, settings.strategy_min_trade_fee_rate)
        fee_amount = round(trade_size * fee_rate, 6)
        net_amount = round(trade_size - fee_amount, 6)

        if net_amount <= 0:
            logger.warning("Net amount non-positive after fee: user=%d", user.id)
            return False

        # Transfer fee to FEES_WALLET
        fee_tx_hash = None
        if settings.collect_fees_onchain and fee_amount > 0 and settings.fees_wallet:
            try:
                fee_tx_hash = await self._web3.transfer_usdc(
                    private_key=private_key,
                    to_address=settings.fees_wallet,
                    amount_usdc=fee_amount,
                )
            except Exception:
                logger.exception("Fee transfer failed: user=%d", user.id)
                await self._insert_trade(
                    user, signal, trade_id, trade_size, net_amount,
                    fee_rate, fee_amount, None, priority, TradeStatus.FAILED,
                )
                return False

        # Place BUY order
        try:
            result = await self._poly.place_market_order(
                private_key=private_key,
                token_id=signal.token_id,
                side="BUY",
                amount_usdc=net_amount,
            )
        except Exception:
            logger.exception("BUY order failed: user=%d", user.id)
            await self._insert_trade(
                user, signal, trade_id, trade_size, net_amount,
                fee_rate, fee_amount, fee_tx_hash, priority, TradeStatus.FAILED,
            )
            return False

        status = TradeStatus.FILLED if result.success else TradeStatus.FAILED

        await self._insert_trade(
            user, signal, trade_id, trade_size, net_amount,
            fee_rate, fee_amount, fee_tx_hash, priority, status,
            tx_hash=result.order_id if result.success else None,
            shares=result.filled_size,
            price=result.avg_price or signal.max_price,
        )

        if result.success:
            await self._notify_trade(user, signal, net_amount, fee_amount, status)

        logger.info(
            "BUY: user=%d strategy=%s amount=%.2f fee=%.4f status=%s",
            user.id, signal.strategy_id, net_amount, fee_amount, status.value,
        )
        return result.success

    async def _execute_sell(
        self, user, signal, sus, trade_size, priority, private_key, trade_id,
    ) -> bool:
        """SELL: no fee, place order."""
        try:
            result = await self._poly.place_market_order(
                private_key=private_key,
                token_id=signal.token_id,
                side="SELL",
                amount_usdc=trade_size,
            )
        except Exception:
            logger.exception("SELL order failed: user=%d", user.id)
            await self._insert_trade(
                user, signal, trade_id, trade_size, trade_size,
                0, 0, None, priority, TradeStatus.FAILED,
            )
            return False

        status = TradeStatus.FILLED if result.success else TradeStatus.FAILED

        await self._insert_trade(
            user, signal, trade_id, trade_size, trade_size,
            0, 0, None, priority, status,
            tx_hash=result.order_id if result.success else None,
            shares=result.filled_size,
            price=result.avg_price or signal.max_price,
        )

        if result.success:
            await self._notify_trade(user, signal, trade_size, 0, status)

        logger.info(
            "SELL: user=%d strategy=%s amount=%.2f status=%s",
            user.id, signal.strategy_id, trade_size, status.value,
        )
        return result.success

    # ── Helpers ───────────────────────────────────────────────────────

    async def _insert_trade(
        self, user, signal, trade_id, gross, net,
        fee_rate, fee_amount, fee_tx_hash, priority, status,
        tx_hash=None, shares=0.0, price=0.0,
    ) -> None:
        """Insert a trade record into the unified trades table."""
        async with async_session() as session:
            trade = Trade(
                trade_id=trade_id,
                user_id=user.id,
                market_id=signal.token_id,
                market_slug=signal.market_slug,
                token_id=signal.token_id,
                side=TradeSide.BUY if signal.action == "BUY" else TradeSide.SELL,
                price=price or signal.max_price,
                gross_amount_usdc=gross,
                fee_amount_usdc=fee_amount,
                net_amount_usdc=net,
                shares=shares,
                status=status,
                tx_hash=tx_hash,
                # Strategy-specific fields
                strategy_id=signal.strategy_id,
                strategy_fee_rate=fee_rate,
                strategy_fee_amount=fee_amount,
                strategy_fee_tx_hash=fee_tx_hash,
                execution_priority=priority,
                is_paper=False,
                executed_at=datetime.utcnow() if status == TradeStatus.FILLED else None,
            )
            session.add(trade)
            await session.commit()

    async def _notify_trade(self, user, signal, amount, fee, status) -> None:
        """Send trade notification via TopicRouter."""
        emoji = "✅" if status == TradeStatus.FILLED else "❌"
        text = (
            f"{emoji} *STRATÉGIE — {signal.action}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Stratégie : `{signal.strategy_id}`\n"
            f"🎯 Marché : {signal.market_slug[:50]}\n"
            f"💰 Montant : {amount:.2f} USDC\n"
            f"💸 Fee : {fee:.4f} USDC\n"
            f"📈 Side : {signal.side} — {signal.action}"
        )

        try:
            # Try per-user router first
            from bot.services.topic_router import TopicRouter
            user_router = await TopicRouter.for_user(user.id, self._bot)
            router = user_router or self._topic_router

            if router and router.is_enabled:
                await router.send_strategy_signal(text)
            else:
                # Fallback to DM
                await self._bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    parse_mode="Markdown",
                )
        except Exception:
            logger.exception("Failed to notify user=%d", user.id)

    async def _update_signal_stats(self, signal, executed, skipped, subs) -> None:
        """Update the signal audit record with execution stats."""
        try:
            from sqlalchemy import desc
            async with async_session() as session:
                from bot.models.strategy_signal import StrategySignal
                record = (
                    await session.execute(
                        select(StrategySignal)
                        .where(StrategySignal.strategy_id == signal.strategy_id)
                        .order_by(desc(StrategySignal.created_at))
                        .limit(1)
                    )
                ).scalar_one_or_none()

                if record:
                    record.subscribers_count = len(subs)
                    record.executed_count = executed
                    record.skipped_count = skipped
                    await session.commit()
        except Exception:
            logger.debug("Failed to update signal stats")
