"""Main entry point for the WENPOLYMARKET V3 Smart CopyTrading Bot."""

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from bot.config import settings
from bot.db.session import init_db, async_session
from bot.models.user import User
from bot.models.trade import Trade, TradeStatus, TradeSide
from bot.handlers.start import get_start_handler, get_setup_group_handler
from bot.handlers.settings import get_settings_handler
from bot.handlers.balance import get_balance_handlers
from bot.handlers.controls import get_control_handlers
from bot.handlers.admin import get_admin_handlers
from bot.handlers.deposit import get_deposit_handlers
from bot.handlers.menu import get_menu_handlers
from bot.handlers.withdraw import get_withdraw_handler
from bot.handlers.analytics import get_analytics_handlers
from bot.handlers.group_setup import get_group_setup_handler
from bot.handlers.mygroup import get_mygroup_handlers
from bot.handlers.group_actions import get_group_action_handlers
from bot.handlers.signals_menu import get_signals_handlers
from bot.handlers.strategies_menu import get_strategies_menu_handler, get_strategy_wallet_handler
from bot.handlers.strategy_status import get_strategy_status_handlers
from bot.handlers.strategy_settings import get_strategy_settings_handlers
from bot.services.monitor import MultiMasterMonitor
from bot.services.clob_ws_monitor import ClobWsMonitor, RawWsEvent
from bot.services.copytrade import CopyTradeEngine
from bot.services.rate_limiter import init_rate_limiter
from bot.services.scheduler import (
    reset_daily_limits,
    cleanup_expired_otps,
    health_check,
    settle_trades,
    reset_strategy_daily_counters,
    snapshot_market_prices,
)

# Strategy engine imports
from bot.services.strategy_listener import StrategyListener
from bot.services.strategy_executor import StrategyExecutor
from bot.services.strategy_resolver import StrategyResolver
from bot.services.strategy_gas_manager import StrategyGasManager
from bot.services.perf_fee_service import collect_daily_perf_fees

# V3 — Smart Analysis imports
from bot.services.topic_router import TopicRouter
from bot.services.signal_scorer import SignalScorer
from bot.services.trader_tracker import TraderTracker
from bot.services.market_intel import MarketIntelService
from bot.services.position_manager import PositionManager
from bot.services.portfolio_manager import PortfolioManager
from bot.services.smart_filter import SmartFilter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_application() -> Application:
    """Build and configure the Telegram bot application."""
    app = Application.builder().token(settings.telegram_token).build()

    # ── Group action interceptor (MUST be group=-1, before ConversationHandler) ──
    # Intercepts set_* / menu_* callbacks in group context:
    #   • Toggles → flip in DB + refresh topic menu
    #   • Value inputs / complex flows → redirect to DM
    # Raises ApplicationHandlerStop so ConversationHandler (group=0) never fires in groups.
    for handler in get_group_action_handlers():
        app.add_handler(handler, group=-1)

    app.add_handler(get_start_handler())
    app.add_handler(get_setup_group_handler())  # setup_my_group from any screen
    app.add_handler(get_settings_handler())
    app.add_handler(get_withdraw_handler())
    for handler in get_deposit_handlers():
        app.add_handler(handler)

    for handler in get_menu_handlers():
        app.add_handler(handler)
    for handler in get_balance_handlers():
        app.add_handler(handler)
    for handler in get_control_handlers():
        app.add_handler(handler)
    for handler in get_admin_handlers():
        app.add_handler(handler)

    # V3 — Analytics handlers (/analytics, trader stats, portfolio, etc.)
    for handler in get_analytics_handlers():
        app.add_handler(handler)

    # V3 — Signals topic menu (profiles, criteria, smart filter)
    for handler in get_signals_handlers():
        app.add_handler(handler)

    # V3 — Auto-setup: creates forum topics when bot is added as admin to a group
    app.add_handler(get_group_setup_handler())

    # /mygroup — show / manage user's linked group
    for handler in get_mygroup_handlers():
        app.add_handler(handler)

    # ── Strategy handlers (fusion with Dirto copybot) ──
    app.add_handler(get_strategies_menu_handler())
    app.add_handler(get_strategy_wallet_handler())
    for handler in get_strategy_status_handlers():
        app.add_handler(handler)
    for handler in get_strategy_settings_handlers():
        app.add_handler(handler)

    return app


def setup_scheduler(
    monitor: MultiMasterMonitor,
    bot=None,
    trader_tracker: TraderTracker = None,
    position_manager: PositionManager = None,
    portfolio_manager: PortfolioManager = None,
    topic_router: TopicRouter = None,
) -> AsyncIOScheduler:
    """Configure periodic background tasks."""
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        reset_daily_limits,
        "cron", hour=0, minute=0,
        id="reset_daily_limits",
    )

    scheduler.add_job(
        cleanup_expired_otps,
        "interval", minutes=10,
        id="cleanup_otps",
    )

    scheduler.add_job(
        health_check,
        "interval", minutes=5,
        id="health_check",
    )

    # Settle resolved trades (paper + live) every 2 minutes
    # V3: passes topic_router + trader_tracker for routing + performance tracking
    scheduler.add_job(
        lambda: settle_trades(
            bot=bot,
            topic_router=topic_router,
            trader_tracker=trader_tracker,
        ),
        "interval", minutes=2,
        id="settle_trades",
    )

    # Refresh watched wallets every 60s so new follows are picked up quickly
    scheduler.add_job(
        monitor.refresh_watched_wallets,
        "interval", seconds=60,
        id="refresh_watched_wallets",
    )

    # ── V3 Scheduled Jobs ──────────────────────────────────────

    # Recalculate trader stats every 15 minutes
    if trader_tracker:
        async def refresh_all_trader_stats():
            """Recalculate stats for all watched wallets.

            On auto-pause, alert each subscriber who follows that trader
            via their own group (multi-tenant).
            """
            try:
                from bot.db.session import async_session as _as
                from bot.models.user import User
                from bot.services.topic_router import TopicRouter
                from bot.services.user_service import get_or_create_settings
                from sqlalchemy import select

                for wallet in monitor.watched_wallets:
                    await trader_tracker.recalculate_stats(wallet)
                    if await trader_tracker.check_auto_pause(wallet):
                        short = f"{wallet[:6]}...{wallet[-4:]}"
                        alert_text = (
                            f"⚠️ *Trader auto-pausé*\n\n"
                            f"`{short}` a été mis en pause automatiquement "
                            f"(win rate en dessous du seuil)."
                        )
                        # Alert each subscriber who follows this wallet
                        try:
                            async with _as() as session:
                                users = (await session.execute(select(User).where(
                                    User.is_active == True  # noqa: E712
                                ))).scalars().all()
                            for u in users:
                                try:
                                    us = None
                                    async with _as() as s2:
                                        us = await get_or_create_settings(s2, u)
                                    if us and wallet in (us.followed_wallets or []):
                                        ur = await TopicRouter.for_user(u.id, topic_router._bot)
                                        eff = ur or topic_router
                                        if eff:
                                            await eff.send_alert(alert_text)
                                except Exception:
                                    pass
                        except Exception:
                            # Fallback: send to global admin topic
                            if topic_router:
                                await topic_router.send_alert(alert_text)

                logger.info(
                    "Trader stats refreshed for %d wallets",
                    len(monitor.watched_wallets),
                )
            except Exception as e:
                logger.error("Trader stats refresh failed: %s", e)

        scheduler.add_job(
            refresh_all_trader_stats,
            "interval", minutes=15,
            id="refresh_trader_stats",
        )

    # Check time-based exits every 5 minutes
    if position_manager:
        async def check_time_exits():
            try:
                await position_manager.check_time_exits(time_exit_hours=24)
            except Exception as e:
                logger.error("Time exit check failed: %s", e)

        scheduler.add_job(
            check_time_exits,
            "interval", minutes=5,
            id="check_time_exits",
        )

    # Daily portfolio report at 8:00 UTC — sends to each user's own group
    if portfolio_manager and topic_router:
        async def daily_portfolio_report():
            try:
                from bot.db.session import async_session
                from bot.models.user import User
                from bot.services.topic_router import TopicRouter
                from sqlalchemy import select

                async with async_session() as session:
                    users = (
                        await session.execute(
                            select(User).where(User.is_active == True)  # noqa: E712
                        )
                    ).scalars().all()

                for user in users:
                    report = await portfolio_manager.format_portfolio_report(user.id)
                    # Use user's own group router if available, else global
                    user_router = await TopicRouter.for_user(user.id, topic_router._bot)
                    effective = user_router or topic_router
                    await effective.send_portfolio(report)
            except Exception as e:
                logger.error("Daily portfolio report failed: %s", e)

        scheduler.add_job(
            daily_portfolio_report,
            "cron", hour=8, minute=0,
            id="daily_portfolio_report",
        )

    # ── Strategy scheduled jobs ──────────────────────────────────
    # Reset strategy daily trade counters at midnight
    scheduler.add_job(
        reset_strategy_daily_counters,
        "cron", hour=0, minute=0,
        id="reset_strategy_daily_counters",
    )

    # Collect daily performance fees at midnight UTC
    scheduler.add_job(
        lambda: collect_daily_perf_fees(bot=bot, topic_router=topic_router),
        "cron", hour=0, minute=1,  # 1 min after midnight to avoid race with counter reset
        id="strategy_perf_fees",
    )

    # Snapshot prices for active markets every hour (momentum tracking)
    scheduler.add_job(
        lambda: snapshot_market_prices(polymarket_client=polymarket_client),
        "interval", hours=1,
        id="snapshot_market_prices",
    )

    return scheduler


async def main() -> None:
    """Initialize database and start the bot."""
    logger.info("Starting WENPOLYMARKET V3 Smart CopyTrading Bot...")

    await init_db()
    logger.info("Database initialized.")

    await init_rate_limiter(settings.redis_url)

    app = build_application()
    logger.info("Bot handlers registered.")

    # ── V3: Initialize Smart Analysis services ──────────────────
    from bot.services.polymarket import polymarket_client

    # Topic Router (Telegram group topics)
    # Loads from .env first, then tries DB (auto-setup config)
    topic_router = TopicRouter(bot=app.bot)
    await topic_router.try_load_from_db()  # Override .env with DB if available

    # Trader performance tracker
    trader_tracker = TraderTracker(topic_router=topic_router)

    # Market intelligence
    market_intel = MarketIntelService(polymarket_client=polymarket_client)

    # Position manager (active SL/TP enforcement)
    position_manager = PositionManager(
        polymarket_client=polymarket_client,
        topic_router=topic_router,
        check_interval=15,
    )

    # Portfolio manager (risk controls)
    portfolio_manager = PortfolioManager(
        position_manager=position_manager,
        market_intel_service=market_intel,
    )

    # Signal scorer
    signal_scorer = SignalScorer(
        polymarket_client=polymarket_client,
        trader_tracker=trader_tracker,
        market_intel_service=market_intel,
    )

    # Smart filter
    smart_filter = SmartFilter(
        market_intel_service=market_intel,
        trader_tracker=trader_tracker,
        polymarket_client=polymarket_client,
    )

    # Create CopyTradeEngine with all V3 services injected
    engine = CopyTradeEngine(
        telegram_bot=app.bot,
        signal_scorer=signal_scorer,
        smart_filter=smart_filter,
        portfolio_manager=portfolio_manager,
        position_manager=position_manager,
        trader_tracker=trader_tracker,
        topic_router=topic_router,
    )

    # Wire position manager exit callback to engine
    async def on_position_exit(user_id, position, reason):
        """Called by PositionManager when SL/TP triggers an exit.

        Executes a real SELL order on Polymarket to close the position.
        """
        logger.info(
            "Position exit triggered: user=%d reason=%s market=%s shares=%.4f",
            user_id, reason, position.market_id[:20], position.shares,
        )

        if not position.shares or position.shares <= 0:
            logger.warning("No shares to sell for position user=%d", user_id)
            return

        try:
            from bot.services.crypto import decrypt_private_key
            from bot.services.polymarket import polymarket_client as pm_client

            async with async_session() as session:
                user = await session.get(User, user_id)
                if not user:
                    logger.error("User not found for exit: user_id=%d", user_id)
                    return

                if user.paper_trading:
                    # Paper mode: credit back the proceeds
                    proceeds = position.shares * position.current_price
                    user.paper_balance += proceeds
                    await session.commit()
                    logger.info(
                        "Paper exit: user=%d proceeds=%.2f balance=%.2f",
                        user_id, proceeds, user.paper_balance,
                    )
                    return

                # Live mode: decrypt PK and place SELL order
                if not user.encrypted_private_key:
                    logger.error("No encrypted PK for user=%d", user_id)
                    return

                pk = decrypt_private_key(
                    user.encrypted_private_key,
                    settings.encryption_key,
                )

                try:
                    order_result = await pm_client.place_market_order(
                        private_key=pk,
                        token_id=position.token_id,
                        side="SELL",
                        amount_usdc=position.shares * position.current_price,
                    )

                    if order_result.success:
                        logger.info(
                            "Exit SELL filled: user=%d market=%s shares=%.4f order=%s",
                            user_id, position.market_id[:20],
                            position.shares, order_result.order_id,
                        )
                        # Record the exit trade
                        import uuid
                        exit_trade = Trade(
                            trade_id=str(uuid.uuid4())[:16],
                            user_id=user_id,
                            market_id=position.market_id,
                            token_id=position.token_id,
                            market_question=position.market_question,
                            side=TradeSide.SELL,
                            price=position.current_price,
                            gross_amount_usdc=position.shares * position.current_price,
                            fee_amount_usdc=0,
                            net_amount_usdc=position.shares * position.current_price,
                            shares=order_result.filled_size,
                            status=TradeStatus.FILLED,
                            tx_hash=order_result.order_id,
                            is_paper=False,
                            executed_at=datetime.utcnow(),
                        )
                        session.add(exit_trade)
                        await session.commit()
                    else:
                        logger.error(
                            "Exit SELL failed: user=%d error=%s",
                            user_id, order_result.error,
                        )
                finally:
                    del pk

        except Exception:
            logger.exception("Exit execution failed: user=%d market=%s", user_id, position.market_id[:20])

    position_manager.set_exit_callback(on_position_exit)

    # ── Strategy engine services (fusion with Dirto) ─────────────
    from bot.services.web3_client import polygon_client as web3_client

    strategy_gas_manager = StrategyGasManager(web3_client=web3_client)

    strategy_executor = StrategyExecutor(
        bot=app.bot,
        topic_router=topic_router,
        gas_manager=strategy_gas_manager,
        polymarket_client=polymarket_client,
        web3_client=web3_client,
    )

    strategy_listener = StrategyListener(
        on_signal=strategy_executor.handle_signal,
    )

    strategy_resolver = StrategyResolver(
        bot=app.bot,
        topic_router=topic_router,
        polymarket_client=polymarket_client,
    )

    # Monitor Data API (positions) — poll every N seconds
    monitor = MultiMasterMonitor(
        poll_interval=settings.monitor_poll_interval,
        on_signal=engine.handle_signal,
    )

    # Give signal scorer access to monitor for consensus scoring
    signal_scorer._monitor = monitor

    # Expose services globally so Mini App endpoints can trigger actions
    # (e.g. immediate refresh when a trader is added via the UI)
    from bot.services import _registry as _svc_reg
    _svc_reg.monitor = monitor
    _svc_reg.engine = engine

    # Callback WebSocket: on each CLOB trade, trigger immediate check
    async def handle_ws_event(evt: RawWsEvent) -> None:
        if evt.type in ("last_trade_price", "trade"):
            await monitor.fast_check_all_wallets()

    # Monitor WebSocket CLOB — real-time
    clob_ws_monitor = ClobWsMonitor(on_event=handle_ws_event)

    # Periodic job: sync WS subscriptions with tracked positions
    async def sync_ws_subscriptions():
        """Gather all token_ids from followed wallets' positions for WS."""
        try:
            token_ids: set[str] = set()
            for wallet in monitor.watched_wallets:
                positions = await polymarket_client.get_positions_by_address(wallet)
                for p in positions:
                    if p.token_id:
                        token_ids.add(p.token_id)
            if token_ids:
                await clob_ws_monitor.update_subscriptions(token_ids)
        except Exception as e:
            logger.warning(f"WS subscription sync failed: {e}")

    scheduler = setup_scheduler(
        monitor,
        bot=app.bot,
        trader_tracker=trader_tracker,
        position_manager=position_manager,
        portfolio_manager=portfolio_manager,
        topic_router=topic_router,
    )

    # Sync WS subscriptions every 2 minutes
    scheduler.add_job(
        sync_ws_subscriptions,
        "interval", seconds=120,
        id="sync_ws_subs",
    )

    scheduler.start()
    logger.info("Scheduler started.")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"],
    )
    logger.info("Telegram bot polling started.")

    await monitor.start()
    logger.info(
        f"Multi-master monitor started "
        f"({len(monitor.watched_wallets)} wallet(s) watched)."
    )

    # Start WebSocket + initial token subscription
    await clob_ws_monitor.start()
    asyncio.create_task(sync_ws_subscriptions())

    # V3: Start position manager monitoring loop
    await position_manager.start()
    logger.info("Position manager started (checking every 15s).")

    # ── Strategy engine: start listener + resolver ──
    try:
        await strategy_listener.start()
        logger.info("Strategy listener started (Redis signals:*).")
    except Exception as e:
        logger.warning("Strategy listener failed to start (Redis unavailable?): %s", e)

    await strategy_resolver.start()
    logger.info("Strategy resolver started (polling every %ds).", settings.strategy_resolver_interval)

    # V3: Startup notification
    if topic_router.is_enabled:
        await topic_router.send_admin(
            "🟢 *Bot V3 Started*\n\n"
            f"Wallets watched: {len(monitor.watched_wallets)}\n"
            "Smart Analysis: ✅ Active\n"
            "Signal Scoring: ✅\n"
            "Trader Tracker: ✅\n"
            "Position Manager: ✅\n"
            "Portfolio Manager: ✅\n"
            "Smart Filter: ✅\n"
            f"Strategy Listener: {'✅' if strategy_listener.is_running else '⚠️ Off'}\n"
            f"Strategy Resolver: {'✅' if strategy_resolver.is_running else '⚠️ Off'}"
        )
    logger.info("V3 Smart Analysis services initialized.")

    # Start web dashboard (FastAPI) if enabled
    dashboard_server = None
    if settings.dashboard_enabled:
        import uvicorn
        from bot.web.app import app as dashboard_app

        config = uvicorn.Config(
            dashboard_app,
            host="0.0.0.0",
            port=settings.dashboard_port,
            log_level="info",
        )
        dashboard_server = uvicorn.Server(config)
        asyncio.create_task(dashboard_server.serve())
        logger.info(f"Dashboard started on http://0.0.0.0:{settings.dashboard_port}")

    logger.info("Bot V3 is fully running. Press Ctrl+C to stop.")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Shutting down...")
        if dashboard_server:
            dashboard_server.should_exit = True
        scheduler.shutdown(wait=False)
        await strategy_listener.stop()
        await strategy_resolver.stop()
        await position_manager.stop()
        await monitor.stop()
        await clob_ws_monitor.stop()
        await polymarket_client.close()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
