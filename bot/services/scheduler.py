"""APScheduler tasks — periodic maintenance jobs."""

import logging
from datetime import datetime

from sqlalchemy import update, select

from bot.db.session import async_session
from bot.models.user import User
from bot.models.trade import Trade, TradeStatus, TradeSide
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


async def settle_trades(bot=None, topic_router=None, trader_tracker=None) -> None:
    """Settle ALL trades (paper + live) whose markets have resolved.

    Runs every 2 minutes. For each unsettled FILLED BUY trade:
    - Check market resolution via Polymarket API
    - Calculate PNL: winner gets shares × $1, loser gets $0
    - Store market_outcome and settlement_pnl
    - Paper mode: update paper_balance
    - Notify user of result (auto-delete after 120s)
    """
    from bot.services.polymarket import polymarket_client

    try:
        async with async_session() as session:
            # Find ALL unsettled trades (paper + live)
            result = await session.execute(
                select(Trade).where(
                    Trade.is_settled == False,  # noqa: E712
                    Trade.status == TradeStatus.FILLED,
                    Trade.side == TradeSide.BUY,
                )
            )
            unsettled = list(result.scalars().all())

            if not unsettled:
                return

            # Group by market_id to avoid duplicate API calls
            by_market: dict[str, list[Trade]] = {}
            for trade in unsettled:
                by_market.setdefault(trade.market_id, []).append(trade)

            logger.info(
                f"Checking {len(by_market)} market(s) for "
                f"{len(unsettled)} unsettled trade(s)"
            )

            settled_count = 0
            checked_count = 0
            for market_id, trades in by_market.items():
                try:
                    resolution = await polymarket_client.check_market_resolution(market_id)
                except Exception as e:
                    logger.warning(f"Failed to check resolution for {market_id[:16]}...: {e}")
                    continue
                checked_count += 1
                if resolution is None:
                    continue  # Market still open

                winning_token = resolution.get("winning_token_id", "")
                winning_outcome = resolution.get("winning_outcome", "")

                for trade in trades:
                    # ───────────────────────────────────────────────
                    # BUG FIX: account for partial SELLs that happened
                    # AFTER this BUY. If user sold part of the position
                    # already, only the REMAINING shares get the payout.
                    # ───────────────────────────────────────────────
                    from sqlalchemy import func as _func
                    from bot.models.trade import Trade as _T
                    sells_sum = await session.scalar(
                        select(_func.coalesce(_func.sum(_T.shares), 0.0)).where(
                            _T.user_id == trade.user_id,
                            _T.token_id == trade.token_id,
                            _T.side == TradeSide.SELL,
                            _T.status == TradeStatus.FILLED,
                            _T.created_at >= trade.created_at,
                        )
                    )
                    sold_shares = float(sells_sum or 0)

                    original_shares = trade.shares or (
                        trade.net_amount_usdc / trade.price
                        if trade.price > 0 else 0
                    )
                    remaining_shares = max(0.0, float(original_shares) - sold_shares)

                    # gross_amount = total USDC cost including platform fee
                    # (net_amount was the fee-net amount sent to the CLOB — using
                    # gross for invested gives the true "total cash out" cost)
                    total_invested_gross = trade.gross_amount_usdc or trade.net_amount_usdc
                    # Pro-rate invested to the remaining shares
                    if original_shares > 0:
                        invested = float(total_invested_gross) * (remaining_shares / float(original_shares))
                    else:
                        invested = 0.0

                    won = trade.token_id == winning_token
                    if remaining_shares <= 0:
                        # Whole position was sold before resolution — PnL already
                        # realized via SELL trades. Just mark this BUY as settled.
                        payout = 0.0
                        pnl = 0.0  # do not double-count
                    elif won:
                        payout = remaining_shares * 1.0
                        pnl = payout - invested
                    else:
                        payout = 0.0
                        pnl = -invested

                    trade.is_settled = True
                    trade.settlement_pnl = round(pnl, 4)
                    trade.market_outcome = winning_outcome
                    # Update effective shares to remaining (for accurate reporting)
                    shares = remaining_shares

                    # Credit payout to paper balance
                    if trade.is_paper:
                        user = await session.get(User, trade.user_id)
                        if user:
                            user.paper_balance = (user.paper_balance or 0) + payout

                    settled_count += 1
                    logger.info(
                        f"Settled {'paper' if trade.is_paper else 'live'} "
                        f"trade {trade.trade_id}: "
                        f"{'WIN' if won else 'LOSS'} "
                        f"pnl={pnl:+.2f} payout={payout:.2f}"
                    )

                    # V3: Record trade outcome for trader tracker
                    if trader_tracker and trade.master_wallet:
                        try:
                            from bot.services.smart_filter import SmartFilter
                            market_type = SmartFilter.categorize_market_type(
                                trade.market_question or ""
                            )
                            return_pct = (pnl / invested * 100) if invested > 0 else 0
                            await trader_tracker.record_trade_outcome(
                                wallet=trade.master_wallet,
                                market_type=market_type,
                                won=won,
                                return_pct=return_pct,
                            )
                        except Exception as e:
                            logger.debug(f"Tracker update failed: {e}")

                    # Notify user
                    if bot:
                        await _notify_settlement(
                            bot, session, trade, won, pnl, payout,
                            topic_router=topic_router,
                        )

            if settled_count > 0:
                await session.commit()
                logger.info(f"Settled {settled_count} trade(s) (checked {checked_count}/{len(by_market)} markets)")
            elif checked_count > 0:
                logger.debug(f"Checked {checked_count}/{len(by_market)} markets — none resolved yet")

    except Exception as e:
        logger.error(f"Error settling trades: {e}", exc_info=True)


# Keep old name as alias for backward compat with main.py
settle_paper_trades = settle_trades


async def _notify_settlement(bot, session, trade, won, pnl, payout, topic_router=None):
    """Send settlement notification to user.

    V3: Routes to Portfolio topic based on user preference.
    """
    import asyncio

    try:
        user = await session.get(User, trade.user_id)
        if not user or not user.telegram_id:
            return

        emoji = "🟢" if won else "🔴"
        result_text = "GAGNÉ" if won else "PERDU"
        paper = " 📝 PAPER" if trade.is_paper else ""
        q = trade.market_question or trade.market_id[:20]
        outcome = trade.market_outcome or "?"

        text = (
            f"{emoji} *MARCHÉ RÉSOLU*{paper}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {q}\n"
            f"🏆 Résultat : *{outcome}* → *{result_text}*\n"
            f"💰 Mise : {trade.net_amount_usdc:.2f} USDC\n"
            f"💵 Payout : {payout:.2f} USDC\n"
            f"📈 P&L : *{pnl:+.2f} USDC*"
        )

        # V3: Route to Portfolio topic
        if topic_router:
            from bot.services.user_service import get_or_create_settings
            us = await get_or_create_settings(session, user)
            notif_mode = getattr(us, "notification_mode", "dm")

            await topic_router.notify_user(
                user_telegram_id=user.telegram_id,
                text=text,
                notification_mode=notif_mode,
                topic="portfolio",
            )
        else:
            # Fallback: DM only
            msg = await bot.send_message(
                chat_id=user.telegram_id,
                text=text,
                parse_mode="Markdown",
            )

            async def _auto_del():
                await asyncio.sleep(120)
                try:
                    await msg.delete()
                except Exception:
                    pass
            asyncio.create_task(_auto_del())

    except Exception as e:
        logger.error(f"Settlement notification error: {e}")


async def reset_strategy_daily_counters() -> None:
    """Reset strategy daily trade counters. Runs at midnight UTC."""
    from bot.models.strategy_user_settings import StrategyUserSettings
    async with async_session() as session:
        await session.execute(
            update(StrategyUserSettings).values(trades_today=0)
        )
        await session.commit()
    logger.info("Strategy daily trade counters reset")


async def snapshot_market_prices(polymarket_client=None) -> None:
    """Snapshot prices for active markets and compute momentum.

    Runs every hour. Only tracks markets with open positions (copy + strategy).
    Shifts price history: current → 1h_ago, 1h_ago → 6h (every 6th call),
    6h_ago → 24h (every 24th call).
    """
    from bot.models.market_intel import MarketIntel as MarketIntelModel

    try:
        async with async_session() as session:
            # 1. Find distinct market_ids with open positions
            #    Copy trades: not settled, BUY, FILLED
            #    Strategy trades: not resolved, FILLED/PENDING
            result = await session.execute(
                select(Trade.market_id).where(
                    Trade.side == TradeSide.BUY,
                    Trade.status == TradeStatus.FILLED,
                    Trade.is_settled == False,  # noqa: E712
                ).distinct()
            )
            copy_markets = {r[0] for r in result.all()}

            result = await session.execute(
                select(Trade.market_id).where(
                    Trade.strategy_id.isnot(None),
                    Trade.resolved_at.is_(None),
                    Trade.status.in_([TradeStatus.FILLED, TradeStatus.PENDING]),
                ).distinct()
            )
            strategy_markets = {r[0] for r in result.all()}

            active_markets = copy_markets | strategy_markets

            if not active_markets:
                return

            logger.debug(
                "Price snapshot: %d active market(s) to track", len(active_markets)
            )

            # 2. For each market, fetch current price and update history
            updated = 0
            for market_id in active_markets:
                try:
                    # Fetch current price from Gamma API
                    current_price = await _fetch_market_price(
                        market_id, polymarket_client
                    )
                    if current_price is None:
                        continue

                    # Get or create MarketIntel row
                    intel = (
                        await session.execute(
                            select(MarketIntelModel).where(
                                MarketIntelModel.market_id == market_id
                            )
                        )
                    ).scalar_one_or_none()

                    if not intel:
                        intel = MarketIntelModel(market_id=market_id)
                        session.add(intel)

                    # Shift price history
                    old_1h = intel.price_1h_ago
                    old_6h = intel.price_6h_ago

                    # 24h_ago gets the 6h value (called every hour,
                    # so after 24 calls the oldest 6h snapshot is ~24h old)
                    # Simpler approach: only overwrite if None or every 6th/24th hour
                    # For simplicity, always shift down:
                    # price_24h_ago ← price_6h_ago (refreshed roughly every 6h)
                    # price_6h_ago  ← price_1h_ago (refreshed roughly every 6h)
                    # price_1h_ago  ← price_current (refreshed every hour)

                    # Only shift 6h/24h every 6 calls (≈ every 6 hours)
                    # We use the hour of the day as a simple modulo trigger
                    hour_now = datetime.utcnow().hour
                    if hour_now % 6 == 0:
                        intel.price_24h_ago = old_6h
                        intel.price_6h_ago = old_1h

                    intel.price_1h_ago = intel.price_current
                    intel.price_current = current_price

                    # Compute momentum_1h
                    if intel.price_1h_ago and intel.price_1h_ago > 0:
                        intel.momentum_1h = round(
                            (current_price - intel.price_1h_ago)
                            / intel.price_1h_ago
                            * 100,
                            2,
                        )
                    else:
                        intel.momentum_1h = None

                    intel.last_updated = datetime.utcnow()
                    updated += 1

                except Exception:
                    logger.debug("Price snapshot failed for %s", market_id[:16])

            if updated:
                await session.commit()
                logger.info(
                    "Price snapshot: updated %d/%d active markets",
                    updated, len(active_markets),
                )

    except Exception:
        logger.exception("Error in snapshot_market_prices")


async def _fetch_market_price(market_id: str, polymarket_client=None) -> float | None:
    """Fetch current YES price for a market from Gamma API."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={"condition_id": market_id, "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()

            if not data:
                return None

            market = data[0]
            outcome_prices_str = market.get("outcomePrices", "")
            if outcome_prices_str:
                prices = [float(p.strip()) for p in outcome_prices_str.split(",")]
                if prices:
                    return prices[0]
    except Exception:
        pass
    return None


async def health_check() -> None:
    """Periodic health check — verify DB and services. Runs every 5 minutes."""
    try:
        async with async_session() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        logger.debug("Health check: DB OK")
    except Exception as e:
        logger.error(f"Health check failed: {e}")
