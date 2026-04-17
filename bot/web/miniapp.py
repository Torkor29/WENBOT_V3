"""Telegram Mini App — FastAPI router with all API endpoints."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func, and_

from bot.db.session import async_session
from bot.models.user import User
from bot.models.trade import Trade, TradeStatus, TradeSide
from bot.models.settings import UserSettings
from bot.models.strategy import Strategy, StrategyStatus, StrategyVisibility
from bot.models.subscription import Subscription
from bot.models.strategy_user_settings import StrategyUserSettings
from bot.web.auth import validate_init_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/miniapp/api")


# ── Auth dependency ──────────────────────────────────────────────


async def get_current_user(request: Request) -> User:
    """Extract and validate Telegram initData, return DB user."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("tma "):
        raise HTTPException(401, "Missing Authorization: tma <initData>")

    init_data = auth[4:]
    tg_user = validate_init_data(init_data)
    if not tg_user:
        raise HTTPException(401, "Invalid or expired initData")

    tg_id = tg_user.get("id")
    if not tg_id:
        raise HTTPException(401, "No user ID in initData")

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == int(tg_id))
        )
        user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(404, "User not registered — use /start in the bot first")

    return user


# ── Models for request/response ──────────────────────────────────


class SettingsUpdate(BaseModel):
    fixed_amount: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    stop_loss_enabled: Optional[bool] = None
    take_profit_enabled: Optional[bool] = None
    max_trade_usdc: Optional[float] = None
    paper_trading: Optional[bool] = None
    is_paused: Optional[bool] = None
    min_signal_score: Optional[float] = None
    smart_filter_enabled: Optional[bool] = None
    trailing_stop_enabled: Optional[bool] = None
    trailing_stop_pct: Optional[float] = None


class SubscribeRequest(BaseModel):
    strategy_id: str
    trade_size: float = 4.0


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """User profile + wallet info."""
    async with async_session() as session:
        # Reload with relationships
        result = await session.execute(
            select(User).where(User.id == user.id)
        )
        u = result.scalar_one()

        # Count active subscriptions
        sub_count = await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.user_id == u.id,
                Subscription.is_active == True,  # noqa: E712
            )
        ) or 0

        # Count followed wallets
        settings = u.settings
        followed_count = len(settings.followed_wallets) if settings and settings.followed_wallets else 0

    return {
        "id": u.id,
        "telegram_id": u.telegram_id,
        "username": u.telegram_username,
        "wallet_address": u.wallet_address,
        "wallet_auto_created": u.wallet_auto_created,
        "strategy_wallet_address": u.strategy_wallet_address,
        "is_active": u.is_active,
        "is_paused": u.is_paused,
        "paper_trading": u.paper_trading,
        "paper_balance": round(u.paper_balance, 2),
        "daily_limit_usdc": u.daily_limit_usdc,
        "daily_spent_usdc": round(u.daily_spent_usdc, 2),
        "followed_wallets_count": followed_count,
        "active_subscriptions": sub_count,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("/copy/positions")
async def get_copy_positions(user: User = Depends(get_current_user)):
    """Open copy-trading positions (BUY trades not yet settled)."""
    async with async_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711 — copy trades only
                Trade.side == TradeSide.BUY,
                Trade.status == TradeStatus.FILLED,
                Trade.is_settled == False,  # noqa: E712
            ).order_by(Trade.created_at.desc()).limit(50)
        )
        trades = result.scalars().all()

    return {
        "positions": [
            {
                "trade_id": t.trade_id,
                "market_question": t.market_question or t.market_id[:30],
                "price": round(t.price, 4),
                "amount": round(t.net_amount_usdc, 2),
                "shares": round(t.shares, 4),
                "master_wallet": f"{t.master_wallet[:6]}...{t.master_wallet[-4:]}" if t.master_wallet else "",
                "is_paper": t.is_paper,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in trades
        ],
        "count": len(trades),
    }


@router.get("/copy/trades")
async def get_copy_trades(
    limit: int = 20,
    user: User = Depends(get_current_user),
):
    """Recent copy-trading trade history."""
    async with async_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            ).order_by(Trade.created_at.desc()).limit(min(limit, 50))
        )
        trades = result.scalars().all()

    return {
        "trades": [
            {
                "trade_id": t.trade_id,
                "market_question": t.market_question or t.market_id[:30],
                "side": t.side.value.upper(),
                "price": round(t.price, 4),
                "amount": round(t.net_amount_usdc, 2),
                "shares": round(t.shares, 4),
                "is_paper": t.is_paper,
                "is_settled": t.is_settled,
                "settlement_pnl": round(t.settlement_pnl, 2) if t.settlement_pnl else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in trades
        ],
        "count": len(trades),
    }


@router.get("/copy/traders")
async def get_copy_traders(user: User = Depends(get_current_user)):
    """Followed traders with basic stats."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.id == user.id)
        )
        u = result.scalar_one()
        settings = u.settings
        wallets = settings.followed_wallets if settings and settings.followed_wallets else []

        traders = []
        for w in wallets:
            trade_count = await session.scalar(
                select(func.count(Trade.id)).where(
                    Trade.user_id == user.id,
                    Trade.master_wallet == w.lower(),
                    Trade.status == TradeStatus.FILLED,
                )
            ) or 0
            volume = await session.scalar(
                select(func.sum(Trade.gross_amount_usdc)).where(
                    Trade.user_id == user.id,
                    Trade.master_wallet == w.lower(),
                    Trade.status == TradeStatus.FILLED,
                )
            ) or 0.0
            traders.append({
                "wallet": w,
                "wallet_short": f"{w[:6]}...{w[-4:]}",
                "trade_count": trade_count,
                "volume": round(volume, 2),
            })

    return {"traders": traders, "count": len(traders)}


@router.get("/copy/stats")
async def get_copy_stats(user: User = Depends(get_current_user)):
    """Copy trading performance summary."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        # Total filled trades
        total = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0

        # Today trades
        today = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
                Trade.created_at >= today_start,
            )
        ) or 0

        # Total volume
        volume = await session.scalar(
            select(func.sum(Trade.gross_amount_usdc)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0.0

        # PnL from settled trades
        total_pnl = await session.scalar(
            select(func.sum(Trade.settlement_pnl)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.is_settled == True,  # noqa: E712
                Trade.settlement_pnl != None,  # noqa: E711
            )
        ) or 0.0

        # Open positions count
        open_count = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.side == TradeSide.BUY,
                Trade.status == TradeStatus.FILLED,
                Trade.is_settled == False,  # noqa: E712
            )
        ) or 0

    return {
        "total_trades": total,
        "trades_today": today,
        "total_volume": round(volume, 2),
        "total_pnl": round(total_pnl, 2),
        "open_positions": open_count,
    }


@router.get("/strategies")
async def get_strategies(user: User = Depends(get_current_user)):
    """List available strategies (public + active)."""
    async with async_session() as session:
        result = await session.execute(
            select(Strategy).where(
                Strategy.visibility == StrategyVisibility.PUBLIC,
                Strategy.status.in_([StrategyStatus.ACTIVE, StrategyStatus.TESTING]),
            ).order_by(Strategy.total_pnl.desc())
        )
        strategies = result.scalars().all()

        # Get user's active subscriptions
        subs = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.is_active == True,  # noqa: E712
            )
        )
        active_sub_ids = {s.strategy_id for s in subs.scalars().all()}

    return {
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "status": s.status.value,
                "total_trades": s.total_trades,
                "total_pnl": round(s.total_pnl, 2),
                "win_rate": round(s.win_rate, 1),
                "min_trade_size": s.min_trade_size,
                "max_trade_size": s.max_trade_size,
                "subscribed": s.id in active_sub_ids,
            }
            for s in strategies
        ],
    }


@router.get("/strategies/subscriptions")
async def get_subscriptions(user: User = Depends(get_current_user)):
    """User's strategy subscriptions."""
    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
            ).order_by(Subscription.created_at.desc())
        )
        subs = result.scalars().all()

    return {
        "subscriptions": [
            {
                "id": s.id,
                "strategy_id": s.strategy_id,
                "strategy_name": s.strategy.name if s.strategy else s.strategy_id,
                "trade_size": s.trade_size,
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in subs
        ],
    }


@router.get("/strategies/trades")
async def get_strategy_trades(
    limit: int = 20,
    user: User = Depends(get_current_user),
):
    """Strategy trade history for this user."""
    async with async_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.strategy_id != None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            ).order_by(Trade.created_at.desc()).limit(min(limit, 50))
        )
        trades = result.scalars().all()

    return {
        "trades": [
            {
                "trade_id": t.trade_id,
                "strategy_id": t.strategy_id,
                "market_question": t.market_question or t.market_id[:30],
                "side": t.side.value.upper(),
                "price": round(t.price, 4),
                "amount": round(t.net_amount_usdc, 2),
                "shares": round(t.shares, 4),
                "result": t.result,
                "pnl": round(t.pnl, 2) if t.pnl is not None else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in trades
        ],
    }


@router.get("/strategies/stats")
async def get_strategy_stats(user: User = Depends(get_current_user)):
    """Strategy performance summary."""
    async with async_session() as session:
        total = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id != None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0

        total_pnl = await session.scalar(
            select(func.sum(Trade.pnl)).where(
                Trade.user_id == user.id,
                Trade.strategy_id != None,  # noqa: E711
                Trade.pnl != None,  # noqa: E711
            )
        ) or 0.0

        wins = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id != None,  # noqa: E711
                Trade.result == "WON",
            )
        ) or 0

        resolved = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id != None,  # noqa: E711
                Trade.result != None,  # noqa: E711
            )
        ) or 0

        # Active subs
        subs = await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.user_id == user.id,
                Subscription.is_active == True,  # noqa: E712
            )
        ) or 0

    return {
        "total_trades": total,
        "total_pnl": round(total_pnl, 2),
        "wins": wins,
        "resolved": resolved,
        "win_rate": round((wins / resolved) * 100, 1) if resolved > 0 else 0,
        "active_subscriptions": subs,
    }


@router.get("/settings")
async def get_settings(user: User = Depends(get_current_user)):
    """Get user's copy-trading settings."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.id == user.id)
        )
        u = result.scalar_one()
        s = u.settings

    if not s:
        return {"error": "No settings found"}

    return {
        "paper_trading": u.paper_trading,
        "is_paused": u.is_paused,
        "fixed_amount": s.fixed_amount,
        "max_trade_usdc": s.max_trade_usdc,
        "stop_loss_enabled": s.stop_loss_enabled,
        "stop_loss_pct": s.stop_loss_pct,
        "take_profit_enabled": s.take_profit_enabled,
        "take_profit_pct": s.take_profit_pct,
        "min_signal_score": s.min_signal_score,
        "smart_filter_enabled": s.smart_filter_enabled,
        "trailing_stop_enabled": s.trailing_stop_enabled,
        "trailing_stop_pct": s.trailing_stop_pct,
        "daily_limit_usdc": u.daily_limit_usdc,
        "followed_wallets": s.followed_wallets or [],
    }


@router.post("/settings")
async def update_settings(
    body: SettingsUpdate,
    user: User = Depends(get_current_user),
):
    """Update user settings (partial)."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.id == user.id)
        )
        u = result.scalar_one()
        s = u.settings

        if not s:
            raise HTTPException(404, "No settings found")

        updates = body.model_dump(exclude_none=True)
        user_fields = {"paper_trading", "is_paused"}

        for key, value in updates.items():
            if key in user_fields:
                setattr(u, key, value)
            elif hasattr(s, key):
                setattr(s, key, value)

        await session.commit()

    return {"ok": True, "updated": list(updates.keys())}
