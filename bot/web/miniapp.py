"""Telegram Mini App — FastAPI router with all API endpoints."""

import logging
import urllib.parse
from datetime import datetime, timedelta, date
from typing import Optional, Any

import httpx
from eth_account import Account
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from web3 import Web3

from bot.config import settings as cfg
from bot.db.session import async_session
from bot.models.user import User
from bot.models.trade import Trade, TradeStatus, TradeSide
from bot.models.settings import UserSettings, SizingMode, GasMode
from bot.models.strategy import Strategy, StrategyStatus, StrategyVisibility
from bot.models.subscription import Subscription
from bot.services.crypto import decrypt_private_key, encrypt_private_key
from bot.services.user_service import save_wallet, get_or_create_strategy_settings
from bot.services.web3_client import polygon_client as web3_client
from bot.web.auth import validate_init_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/miniapp/api")


# ── Auth dependency ──────────────────────────────────────────────
async def get_current_user(request: Request) -> User:
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
        result = await session.execute(select(User).where(User.telegram_id == int(tg_id)))
        user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not registered — use /start in the bot first")
    return user


# ── Request models ───────────────────────────────────────────────
# NOTE: only fields with actual backend wiring are exposed.
# Removed: notify_on_buy/sell/sl_tp (no DB column), time_exit_*, scale_out_*,
#          auto_pause_cold_traders, cold_trader_threshold, hot_streak_boost,
#          use_gamma_monitor, use_ws_monitor, auto_bridge_sol (cosmetic only)
class SettingsUpdate(BaseModel):
    # User flags
    paper_trading: Optional[bool] = None
    is_paused: Optional[bool] = None
    is_active: Optional[bool] = None
    daily_limit_usdc: Optional[float] = None

    # Capital & sizing
    allocated_capital: Optional[float] = None
    sizing_mode: Optional[str] = None          # fixed | percent | proportional | kelly
    fixed_amount: Optional[float] = None
    percent_per_trade: Optional[float] = None
    multiplier: Optional[float] = None
    min_trade_usdc: Optional[float] = None
    max_trade_usdc: Optional[float] = None

    # Risk
    stop_loss_enabled: Optional[bool] = None
    stop_loss_pct: Optional[float] = None
    take_profit_enabled: Optional[bool] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_enabled: Optional[bool] = None
    trailing_stop_pct: Optional[float] = None

    # Copy behaviour
    copy_delay_seconds: Optional[int] = None
    manual_confirmation: Optional[bool] = None
    confirmation_threshold_usdc: Optional[float] = None

    # Gas
    gas_mode: Optional[str] = None             # normal | fast | ultra | instant

    # Filters
    categories: Optional[list] = None
    blacklisted_markets: Optional[list] = None
    max_expiry_days: Optional[int] = None
    trader_filters: Optional[dict] = None

    # Portfolio risk
    max_positions: Optional[int] = None
    max_category_exposure_pct: Optional[float] = None
    max_direction_bias_pct: Optional[float] = None

    # Smart filter & signal scoring
    signal_scoring_enabled: Optional[bool] = None
    min_signal_score: Optional[float] = None
    scoring_criteria: Optional[dict] = None
    smart_filter_enabled: Optional[bool] = None
    min_trader_winrate_for_type: Optional[float] = None
    min_trader_trades_for_type: Optional[int] = None
    skip_coin_flip: Optional[bool] = None
    min_conviction_pct: Optional[float] = None
    max_price_drift_pct: Optional[float] = None

    # Notifications
    notification_mode: Optional[str] = None    # dm | group | both

    # Strategy bucket
    strategy_trade_fee_rate: Optional[float] = None
    strategy_max_trades_per_day: Optional[int] = None
    strategy_is_paused: Optional[bool] = None


class ImportPkReq(BaseModel):
    private_key: str

class WithdrawReq(BaseModel):
    to_address: str
    amount: float

class ExportPkReq(BaseModel):
    confirm: bool

class TraderAddReq(BaseModel):
    wallet: str

class SubscribeRequest(BaseModel):
    trade_size: float = 4.0

class SubscriptionPatch(BaseModel):
    trade_size: Optional[float] = None
    is_active: Optional[bool] = None

class ScoringProfileReq(BaseModel):
    profile: str  # prudent | balanced | aggressive

class ModeChangeReq(BaseModel):
    paper_trading: bool
    confirm_live: bool = False

class TraderFilterReq(BaseModel):
    wallet: str
    excluded_categories: list[str] = []


# Profile presets
SCORING_PROFILES = {
    "prudent": {
        "min_signal_score": 65.0,
        "scoring_criteria": {
            "spread": {"on": True, "w": 20},
            "liquidity": {"on": True, "w": 20},
            "conviction": {"on": True, "w": 20},
            "trader_form": {"on": True, "w": 15},
            "timing": {"on": True, "w": 15},
            "consensus": {"on": True, "w": 10},
        },
        "skip_coin_flip": True,
        "min_conviction_pct": 5.0,
        "max_price_drift_pct": 3.0,
    },
    "balanced": {
        "min_signal_score": 40.0,
        "scoring_criteria": {
            "spread": {"on": True, "w": 15},
            "liquidity": {"on": True, "w": 15},
            "conviction": {"on": True, "w": 20},
            "trader_form": {"on": True, "w": 20},
            "timing": {"on": True, "w": 15},
            "consensus": {"on": True, "w": 15},
        },
        "skip_coin_flip": True,
        "min_conviction_pct": 2.0,
        "max_price_drift_pct": 5.0,
    },
    "aggressive": {
        "min_signal_score": 20.0,
        "scoring_criteria": {
            "spread": {"on": False, "w": 0},
            "liquidity": {"on": True, "w": 15},
            "conviction": {"on": True, "w": 35},
            "trader_form": {"on": True, "w": 30},
            "timing": {"on": False, "w": 0},
            "consensus": {"on": True, "w": 20},
        },
        "skip_coin_flip": False,
        "min_conviction_pct": 1.0,
        "max_price_drift_pct": 10.0,
    },
}


def _is_valid_address(addr: str) -> bool:
    try:
        return Web3.is_address(addr)
    except Exception:
        return len(addr) == 42 and addr.startswith("0x")


# ─────────────────────────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────────────────────────
@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        sub_count = await session.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.user_id == u.id,
                Subscription.is_active == True,  # noqa: E712
            )
        ) or 0
        s = u.settings
        followed_count = len(s.followed_wallets) if s and s.followed_wallets else 0

    return {
        "id": u.id,
        "telegram_id": u.telegram_id,
        "username": u.telegram_username,
        "wallet_address": u.wallet_address,
        "wallet_auto_created": u.wallet_auto_created,
        "strategy_wallet_address": getattr(u, "strategy_wallet_address", None),
        "is_active": u.is_active,
        "is_paused": u.is_paused,
        "paper_trading": u.paper_trading,
        "live_mode_confirmed": getattr(u, "live_mode_confirmed", False),
        "paper_balance": round(u.paper_balance, 2) if u.paper_balance else 0,
        "paper_initial_balance": round(getattr(u, "paper_initial_balance", 1000) or 1000, 2),
        "daily_limit_usdc": u.daily_limit_usdc,
        "daily_spent_usdc": round(u.daily_spent_usdc, 2) if u.daily_spent_usdc else 0,
        "followed_wallets_count": followed_count,
        "active_subscriptions": sub_count,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


# ─────────────────────────────────────────────────────────────────
# CONTROLS — pause / resume / stop
# ─────────────────────────────────────────────────────────────────
@router.post("/controls/pause")
async def control_pause(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = await session.get(User, user.id)
        u.is_paused = True
        await session.commit()
    logger.info(f"User {user.id} paused copy trading")
    return {"ok": True, "state": "paused"}


@router.post("/controls/resume")
async def control_resume(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = await session.get(User, user.id)
        u.is_paused = False
        u.is_active = True
        await session.commit()
    logger.info(f"User {user.id} resumed copy trading")
    return {"ok": True, "state": "running"}


@router.get("/controls/status")
async def control_status(user: User = Depends(get_current_user)):
    state = "stopped" if not user.is_active else ("paused" if user.is_paused else "running")
    return {
        "state": state,
        "is_active": user.is_active,
        "is_paused": user.is_paused,
        "paper_trading": user.paper_trading,
    }


# ─────────────────────────────────────────────────────────────────
# WALLET (copy)
# ─────────────────────────────────────────────────────────────────
@router.post("/wallet/create")
async def wallet_create(user: User = Depends(get_current_user)):
    if user.wallet_address:
        raise HTTPException(400, "Wallet déjà configuré — supprimez-le d'abord")
    acct = Account.create()
    pk_hex = acct.key.hex()
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        u.wallet_auto_created = True
        await save_wallet(session, u, acct.address, pk_hex, "polygon")
    logger.info(f"User {user.id} created new wallet {acct.address}")
    return {"address": acct.address, "private_key": pk_hex}


@router.post("/wallet/import")
async def wallet_import(body: ImportPkReq, user: User = Depends(get_current_user)):
    pk = body.private_key.strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    if len(pk) != 66:
        raise HTTPException(400, "Clé privée invalide (attendu 64 hex)")
    try:
        acct = Account.from_key(pk)
    except Exception:
        raise HTTPException(400, "Clé privée invalide")
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        u.wallet_auto_created = False
        await save_wallet(session, u, acct.address, pk, "polygon")
    logger.info(f"User {user.id} imported wallet {acct.address}")
    return {"address": acct.address}


@router.get("/wallet/balance")
async def wallet_balance(user: User = Depends(get_current_user)):
    if not user.wallet_address:
        raise HTTPException(404, "No wallet configured")
    usdc = 0.0; matic = 0.0; usdc_error = None; matic_error = None
    try: usdc = await web3_client.get_usdc_balance(user.wallet_address)
    except Exception as e:
        logger.warning(f"get_usdc_balance failed: {e}"); usdc_error = "RPC indisponible"
    try: matic = await web3_client.get_matic_balance(user.wallet_address)
    except Exception as e:
        logger.warning(f"get_matic_balance failed: {e}"); matic_error = "RPC indisponible"
    return {
        "address": user.wallet_address,
        "usdc": round(float(usdc), 4),
        "matic": round(float(matic), 6),
        "usdc_error": usdc_error,
        "matic_error": matic_error,
    }


@router.post("/wallet/withdraw")
async def wallet_withdraw(body: WithdrawReq, user: User = Depends(get_current_user)):
    if not user.wallet_address or not user.encrypted_private_key:
        raise HTTPException(404, "No wallet")
    if body.amount <= 0:
        raise HTTPException(400, "Montant invalide")
    if not _is_valid_address(body.to_address):
        raise HTTPException(400, "Adresse destination invalide")
    try: pk = decrypt_private_key(user.encrypted_private_key, cfg.encryption_key, user.uuid)
    except Exception: raise HTTPException(500, "Impossible de déchiffrer la clé")
    try:
        result = await web3_client.transfer_usdc(
            from_address=user.wallet_address,
            to_address=body.to_address,
            amount_usdc=body.amount,
            private_key=pk,
        )
    except Exception as e:
        logger.error(f"withdraw failed for user {user.id}: {e}")
        raise HTTPException(500, f"Transaction échouée: {e}")
    if not getattr(result, "success", False):
        raise HTTPException(500, getattr(result, "error", None) or "Transaction échouée")
    tx_hash = getattr(result, "tx_hash", None) or ""
    logger.info(f"User {user.id} withdrew {body.amount} USDC to {body.to_address} — tx {tx_hash}")
    return {"tx_hash": tx_hash}


@router.post("/wallet/export-pk")
async def wallet_export_pk(body: ExportPkReq, user: User = Depends(get_current_user)):
    if not body.confirm: raise HTTPException(400, "Confirmation requise")
    if not user.encrypted_private_key: raise HTTPException(404, "No wallet")
    try: pk = decrypt_private_key(user.encrypted_private_key, cfg.encryption_key, user.uuid)
    except Exception: raise HTTPException(500, "Impossible de déchiffrer la clé")
    logger.warning(f"⚠ User {user.id} exported private key via miniapp")
    return {"private_key": pk}


@router.delete("/wallet")
async def wallet_delete(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        u.wallet_address = None
        u.encrypted_private_key = None
        u.wallet_auto_created = False
        await session.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────
# COPY
# ─────────────────────────────────────────────────────────────────
@router.get("/copy/stats")
async def get_copy_stats(user: User = Depends(get_current_user)):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session() as session:
        total = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.status == TradeStatus.FILLED)) or 0  # noqa: E711
        today = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.status == TradeStatus.FILLED, Trade.created_at >= today_start)) or 0
        volume = await session.scalar(select(func.sum(Trade.gross_amount_usdc)).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.status == TradeStatus.FILLED)) or 0.0
        total_pnl = await session.scalar(select(func.sum(Trade.settlement_pnl)).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.is_settled == True, Trade.settlement_pnl.isnot(None))) or 0.0  # noqa: E712,E711
        open_count = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.side == TradeSide.BUY, Trade.status == TradeStatus.FILLED,
            Trade.is_settled == False)) or 0  # noqa: E712
    return {
        "total_trades": total, "trades_today": today,
        "total_volume": round(volume, 2), "total_pnl": round(total_pnl, 2),
        "open_positions": open_count,
    }


@router.get("/copy/positions")
async def get_copy_positions(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(Trade).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.side == TradeSide.BUY, Trade.status == TradeStatus.FILLED,
            Trade.is_settled == False).order_by(Trade.created_at.desc()).limit(50))
        trades = result.scalars().all()
    return {
        "positions": [{
            "trade_id": t.trade_id,
            "market_question": t.market_question or (t.market_id or "")[:40],
            "price": round(t.price or 0, 4),
            "amount": round(t.net_amount_usdc or 0, 2),
            "shares": round(t.shares or 0, 4),
            "master_wallet": f"{t.master_wallet[:6]}...{t.master_wallet[-4:]}" if t.master_wallet else "",
            "master_wallet_full": t.master_wallet or "",
            "is_paper": t.is_paper,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in trades],
        "count": len(trades),
    }


@router.get("/copy/trades")
async def get_copy_trades(limit: int = 20, offset: int = 0, user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(Trade).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.status == TradeStatus.FILLED).order_by(Trade.created_at.desc())
            .limit(min(limit, 50)).offset(max(offset, 0)))
        trades = result.scalars().all()
    return {
        "trades": [{
            "trade_id": t.trade_id,
            "market_question": t.market_question or (t.market_id or "")[:40],
            "side": t.side.value.upper() if t.side else "",
            "price": round(t.price or 0, 4),
            "amount": round(t.net_amount_usdc or 0, 2),
            "shares": round(t.shares or 0, 4),
            "is_paper": t.is_paper,
            "is_settled": t.is_settled,
            "settlement_pnl": round(t.settlement_pnl, 2) if t.settlement_pnl is not None else None,
            "master_wallet": f"{t.master_wallet[:6]}...{t.master_wallet[-4:]}" if t.master_wallet else "",
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in trades],
        "count": len(trades),
    }


@router.get("/copy/traders")
async def get_copy_traders(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        wallets = s.followed_wallets if s and s.followed_wallets else []
        traders = []
        for w in wallets:
            trade_count = await session.scalar(select(func.count(Trade.id)).where(
                Trade.user_id == user.id, Trade.master_wallet == w.lower(),
                Trade.status == TradeStatus.FILLED)) or 0
            volume = await session.scalar(select(func.sum(Trade.gross_amount_usdc)).where(
                Trade.user_id == user.id, Trade.master_wallet == w.lower(),
                Trade.status == TradeStatus.FILLED)) or 0.0
            pnl = await session.scalar(select(func.sum(Trade.settlement_pnl)).where(
                Trade.user_id == user.id, Trade.master_wallet == w.lower(),
                Trade.is_settled == True, Trade.settlement_pnl.isnot(None))) or 0.0  # noqa: E712,E711
            traders.append({
                "wallet": w,
                "wallet_short": f"{w[:6]}...{w[-4:]}",
                "trade_count": trade_count,
                "volume": round(volume, 2),
                "pnl": round(pnl, 2),
            })
    return {"traders": traders, "count": len(traders)}


@router.post("/copy/traders/add")
async def traders_add(body: TraderAddReq, user: User = Depends(get_current_user)):
    w = body.wallet.strip()
    if not _is_valid_address(w):
        raise HTTPException(400, "Adresse Ethereum invalide")
    w_lower = w.lower()
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s: raise HTTPException(500, "User settings missing")
        wallets = list(s.followed_wallets or [])
        if w_lower in [x.lower() for x in wallets]:
            raise HTTPException(409, "Ce trader est déjà suivi")
        wallets.append(w_lower)
        s.followed_wallets = wallets
        await session.commit()
    return {"ok": True, "count": len(wallets)}


@router.delete("/copy/traders/{wallet}")
async def traders_remove(wallet: str, user: User = Depends(get_current_user)):
    w_lower = wallet.strip().lower()
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s: raise HTTPException(500, "User settings missing")
        wallets = [x for x in (s.followed_wallets or []) if x.lower() != w_lower]
        s.followed_wallets = wallets
        await session.commit()
    return {"ok": True, "count": len(wallets)}


@router.get("/copy/traders/{wallet}/stats")
async def trader_detail(wallet: str, user: User = Depends(get_current_user)):
    w_lower = wallet.strip().lower()
    async with async_session() as session:
        total = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.master_wallet == w_lower,
            Trade.status == TradeStatus.FILLED)) or 0
        volume = await session.scalar(select(func.sum(Trade.gross_amount_usdc)).where(
            Trade.user_id == user.id, Trade.master_wallet == w_lower,
            Trade.status == TradeStatus.FILLED)) or 0.0
        pnl = await session.scalar(select(func.sum(Trade.settlement_pnl)).where(
            Trade.user_id == user.id, Trade.master_wallet == w_lower,
            Trade.is_settled == True, Trade.settlement_pnl.isnot(None))) or 0.0  # noqa: E712,E711
        wins = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.master_wallet == w_lower,
            Trade.is_settled == True, Trade.settlement_pnl > 0)) or 0  # noqa: E712
        losses = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.master_wallet == w_lower,
            Trade.is_settled == True, Trade.settlement_pnl <= 0)) or 0  # noqa: E712
        last_trades = (await session.execute(select(Trade).where(
            Trade.user_id == user.id, Trade.master_wallet == w_lower,
            Trade.status == TradeStatus.FILLED).order_by(Trade.created_at.desc()).limit(10))).scalars().all()
    resolved = wins + losses
    return {
        "wallet": wallet,
        "trade_count": total,
        "volume": round(volume, 2),
        "pnl": round(pnl, 2),
        "wins": wins, "losses": losses,
        "win_rate": round(wins / resolved * 100, 1) if resolved else 0,
        "recent_trades": [{
            "market_question": t.market_question or (t.market_id or "")[:40],
            "side": t.side.value.upper() if t.side else "",
            "price": round(t.price or 0, 4),
            "amount": round(t.net_amount_usdc or 0, 2),
            "pnl": round(t.settlement_pnl, 2) if t.settlement_pnl is not None else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in last_trades],
    }


# ─────────────────────────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────────────────────────
@router.get("/strategies")
async def get_strategies(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(Strategy).where(
            Strategy.visibility == StrategyVisibility.PUBLIC,
            Strategy.status.in_([StrategyStatus.ACTIVE, StrategyStatus.TESTING])
        ).order_by(Strategy.total_pnl.desc()))
        strategies = result.scalars().all()
        subs = await session.execute(select(Subscription).where(
            Subscription.user_id == user.id, Subscription.is_active == True))  # noqa: E712
        active_sub_map = {s.strategy_id: s for s in subs.scalars().all()}
    return {"strategies": [{
        "id": s.id, "name": s.name, "description": s.description,
        "status": s.status.value, "total_trades": s.total_trades,
        "total_pnl": round(s.total_pnl, 2), "win_rate": round(s.win_rate, 1),
        "min_trade_size": s.min_trade_size, "max_trade_size": s.max_trade_size,
        "subscribed": s.id in active_sub_map,
        "my_trade_size": active_sub_map[s.id].trade_size if s.id in active_sub_map else None,
    } for s in strategies]}


@router.get("/strategies/subscriptions")
async def get_subscriptions(user: User = Depends(get_current_user)):
    async with async_session() as session:
        subs = (await session.execute(select(Subscription).where(
            Subscription.user_id == user.id).order_by(Subscription.created_at.desc()))).scalars().all()
    return {"subscriptions": [{
        "id": s.id, "strategy_id": s.strategy_id,
        "strategy_name": s.strategy.name if s.strategy else s.strategy_id,
        "trade_size": s.trade_size, "is_active": s.is_active,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    } for s in subs]}


@router.post("/strategies/{strategy_id}/subscribe")
async def strat_subscribe(strategy_id: str, body: SubscribeRequest, user: User = Depends(get_current_user)):
    async with async_session() as session:
        strat = await session.get(Strategy, strategy_id)
        if not strat: raise HTTPException(404, "Strategy not found")
        if strat.status not in (StrategyStatus.ACTIVE, StrategyStatus.TESTING):
            raise HTTPException(400, "Strategy non souscriptible")
        if not (strat.min_trade_size <= body.trade_size <= strat.max_trade_size):
            raise HTTPException(400, f"trade_size doit être entre {strat.min_trade_size} et {strat.max_trade_size}")
        sub = (await session.execute(select(Subscription).where(
            Subscription.user_id == user.id, Subscription.strategy_id == strategy_id))).scalar_one_or_none()
        if sub:
            sub.trade_size = body.trade_size; sub.is_active = True
        else:
            sub = Subscription(user_id=user.id, strategy_id=strategy_id, trade_size=body.trade_size, is_active=True)
            session.add(sub)
        await session.commit(); await session.refresh(sub)
        return {"ok": True, "subscription_id": sub.id}


@router.post("/strategies/{strategy_id}/unsubscribe")
async def strat_unsubscribe(strategy_id: str, user: User = Depends(get_current_user)):
    async with async_session() as session:
        sub = (await session.execute(select(Subscription).where(
            Subscription.user_id == user.id, Subscription.strategy_id == strategy_id))).scalar_one_or_none()
        if not sub: raise HTTPException(404, "Subscription introuvable")
        sub.is_active = False
        await session.commit()
    return {"ok": True}


@router.patch("/strategies/{strategy_id}/subscription")
async def strat_patch_sub(strategy_id: str, body: SubscriptionPatch, user: User = Depends(get_current_user)):
    async with async_session() as session:
        strat = await session.get(Strategy, strategy_id)
        sub = (await session.execute(select(Subscription).where(
            Subscription.user_id == user.id, Subscription.strategy_id == strategy_id))).scalar_one_or_none()
        if not sub: raise HTTPException(404, "Subscription introuvable")
        if body.trade_size is not None:
            if strat and not (strat.min_trade_size <= body.trade_size <= strat.max_trade_size):
                raise HTTPException(400, "trade_size hors bornes")
            sub.trade_size = body.trade_size
        if body.is_active is not None: sub.is_active = body.is_active
        await session.commit()
    return {"ok": True}


@router.get("/strategies/trades")
async def get_strategy_trades(limit: int = 20, offset: int = 0, user: User = Depends(get_current_user)):
    async with async_session() as session:
        trades = (await session.execute(select(Trade).where(
            Trade.user_id == user.id, Trade.strategy_id.isnot(None),
            Trade.status == TradeStatus.FILLED).order_by(Trade.created_at.desc())
            .limit(min(limit, 50)).offset(max(offset, 0)))).scalars().all()
    return {"trades": [{
        "trade_id": t.trade_id, "strategy_id": t.strategy_id,
        "market_question": t.market_question or (t.market_id or "")[:40],
        "side": t.side.value.upper() if t.side else "",
        "price": round(t.price or 0, 4),
        "amount": round(t.net_amount_usdc or 0, 2),
        "shares": round(t.shares or 0, 4),
        "result": getattr(t, "result", None),
        "pnl": round(t.pnl, 2) if getattr(t, "pnl", None) is not None else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in trades]}


@router.get("/strategies/stats")
async def get_strategy_stats(user: User = Depends(get_current_user)):
    async with async_session() as session:
        total = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.strategy_id.isnot(None),
            Trade.status == TradeStatus.FILLED)) or 0  # noqa: E711
        total_pnl = await session.scalar(select(func.sum(Trade.pnl)).where(
            Trade.user_id == user.id, Trade.strategy_id.isnot(None),
            Trade.pnl.isnot(None))) or 0.0  # noqa: E711
        wins = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.strategy_id.isnot(None),
            Trade.result == "WON")) or 0
        resolved = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.strategy_id.isnot(None),
            Trade.result.isnot(None))) or 0  # noqa: E711
        subs = await session.scalar(select(func.count(Subscription.id)).where(
            Subscription.user_id == user.id, Subscription.is_active == True)) or 0  # noqa: E712
    return {
        "total_trades": total, "total_pnl": round(total_pnl, 2),
        "wins": wins, "resolved": resolved,
        "win_rate": round((wins / resolved) * 100, 1) if resolved > 0 else 0,
        "active_subscriptions": subs,
    }


# ─────────────────────────────────────────────────────────────────
# STRATEGY WALLET
# ─────────────────────────────────────────────────────────────────
@router.post("/strategy-wallet/create")
async def strat_wallet_create(user: User = Depends(get_current_user)):
    if getattr(user, "strategy_wallet_address", None):
        raise HTTPException(400, "Wallet stratégie déjà configuré")
    acct = Account.create(); pk_hex = acct.key.hex()
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        u.strategy_wallet_address = acct.address
        u.encrypted_strategy_private_key = encrypt_private_key(pk_hex, cfg.encryption_key, u.uuid)
        u.strategy_wallet_auto_created = True
        await session.commit()
    return {"address": acct.address, "private_key": pk_hex}


@router.post("/strategy-wallet/import")
async def strat_wallet_import(body: ImportPkReq, user: User = Depends(get_current_user)):
    pk = body.private_key.strip()
    if not pk.startswith("0x"): pk = "0x" + pk
    if len(pk) != 66: raise HTTPException(400, "Clé privée invalide")
    try: acct = Account.from_key(pk)
    except Exception: raise HTTPException(400, "Clé privée invalide")
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        u.strategy_wallet_address = acct.address
        u.encrypted_strategy_private_key = encrypt_private_key(pk, cfg.encryption_key, u.uuid)
        u.strategy_wallet_auto_created = False
        await session.commit()
    return {"address": acct.address}


@router.get("/strategy-wallet/balance")
async def strat_wallet_balance(user: User = Depends(get_current_user)):
    addr = getattr(user, "strategy_wallet_address", None)
    if not addr: raise HTTPException(404, "No strategy wallet")
    usdc = 0.0; matic = 0.0; usdc_error = None; matic_error = None
    try: usdc = await web3_client.get_usdc_balance(addr)
    except Exception as e: usdc_error = "RPC indisponible"; logger.warning(f"strat usdc balance: {e}")
    try: matic = await web3_client.get_matic_balance(addr)
    except Exception as e: matic_error = "RPC indisponible"; logger.warning(f"strat matic balance: {e}")
    return {
        "address": addr, "usdc": round(float(usdc), 4), "matic": round(float(matic), 6),
        "usdc_error": usdc_error, "matic_error": matic_error,
    }


@router.delete("/strategy-wallet")
async def strat_wallet_delete(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        u.strategy_wallet_address = None
        u.encrypted_strategy_private_key = None
        u.strategy_wallet_auto_created = False
        await session.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────────
_USER_FIELDS = {"paper_trading", "is_paused", "is_active", "daily_limit_usdc"}
_STRATEGY_FIELDS = {"strategy_trade_fee_rate", "strategy_max_trades_per_day", "strategy_is_paused"}
_STRATEGY_MAP = {
    "strategy_trade_fee_rate": "trade_fee_rate",
    "strategy_max_trades_per_day": "max_trades_per_day",
    "strategy_is_paused": "is_paused",
}
_ENUM_FIELDS = {
    "sizing_mode": SizingMode,
    "gas_mode": GasMode,
}


@router.get("/settings")
async def get_settings(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        strat_s = getattr(u, "strategy_settings", None)

    data: dict[str, Any] = {
        "paper_trading": u.paper_trading,
        "is_paused": u.is_paused,
        "is_active": u.is_active,
        "daily_limit_usdc": u.daily_limit_usdc,
        "daily_spent_usdc": round(u.daily_spent_usdc or 0, 2),
    }
    if s:
        for field in [
            # capital
            "allocated_capital", "sizing_mode", "fixed_amount", "percent_per_trade",
            "multiplier", "min_trade_usdc", "max_trade_usdc",
            # risk
            "stop_loss_enabled", "stop_loss_pct", "take_profit_enabled", "take_profit_pct",
            "trailing_stop_enabled", "trailing_stop_pct",
            # copy
            "copy_delay_seconds", "manual_confirmation", "confirmation_threshold_usdc",
            # gas
            "gas_mode",
            # filters
            "categories", "blacklisted_markets", "max_expiry_days", "trader_filters",
            # portfolio
            "max_positions", "max_category_exposure_pct", "max_direction_bias_pct",
            # scoring / smart
            "signal_scoring_enabled", "min_signal_score", "scoring_criteria",
            "smart_filter_enabled", "min_trader_winrate_for_type", "min_trader_trades_for_type",
            "skip_coin_flip", "min_conviction_pct", "max_price_drift_pct",
            # notifs
            "notification_mode",
            # followed
            "followed_wallets",
        ]:
            if hasattr(s, field):
                val = getattr(s, field)
                if hasattr(val, "value"): val = val.value
                data[field] = val
    if strat_s:
        data["strategy_trade_fee_rate"] = getattr(strat_s, "trade_fee_rate", None)
        data["strategy_max_trades_per_day"] = getattr(strat_s, "max_trades_per_day", None)
        data["strategy_is_paused"] = getattr(strat_s, "is_paused", None)
    return data


@router.post("/settings")
async def update_settings(body: SettingsUpdate, user: User = Depends(get_current_user)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"ok": True, "updated": []}

    # Validations
    if "stop_loss_pct" in updates and not (0 < updates["stop_loss_pct"] <= 100):
        raise HTTPException(400, "stop_loss_pct entre 0 et 100")
    if "take_profit_pct" in updates and not (0 < updates["take_profit_pct"] <= 500):
        raise HTTPException(400, "take_profit_pct entre 0 et 500")
    if "trailing_stop_pct" in updates and not (0 < updates["trailing_stop_pct"] <= 100):
        raise HTTPException(400, "trailing_stop_pct entre 0 et 100")
    if "scale_out_pct" in updates and not (0 < updates["scale_out_pct"] <= 100):
        raise HTTPException(400, "scale_out_pct entre 0 et 100")
    if "time_exit_hours" in updates and not (1 <= updates["time_exit_hours"] <= 720):
        raise HTTPException(400, "time_exit_hours entre 1 et 720")
    if "min_signal_score" in updates and not (0 <= updates["min_signal_score"] <= 100):
        raise HTTPException(400, "min_signal_score entre 0 et 100")
    if "multiplier" in updates and not (0.1 <= updates["multiplier"] <= 10):
        raise HTTPException(400, "multiplier entre 0.1 et 10")
    if "max_positions" in updates and not (1 <= updates["max_positions"] <= 100):
        raise HTTPException(400, "max_positions entre 1 et 100")
    if "copy_delay_seconds" in updates and not (0 <= updates["copy_delay_seconds"] <= 600):
        raise HTTPException(400, "copy_delay_seconds entre 0 et 600")
    if "strategy_trade_fee_rate" in updates and not (0.01 <= updates["strategy_trade_fee_rate"] <= 0.20):
        raise HTTPException(400, "trade_fee_rate entre 1% et 20%")
    if "strategy_max_trades_per_day" in updates and not (1 <= updates["strategy_max_trades_per_day"] <= 200):
        raise HTTPException(400, "max_trades_per_day entre 1 et 200")
    if "fixed_amount" in updates and updates["fixed_amount"] <= 0:
        raise HTTPException(400, "fixed_amount doit être > 0")
    if "gas_mode" in updates and updates["gas_mode"] not in [m.value for m in GasMode]:
        raise HTTPException(400, "gas_mode invalide")
    if "sizing_mode" in updates and updates["sizing_mode"] not in [m.value for m in SizingMode]:
        raise HTTPException(400, "sizing_mode invalide")
    if "notification_mode" in updates and updates["notification_mode"] not in ("dm", "group", "both"):
        raise HTTPException(400, "notification_mode invalide")

    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        need_strat = any(k in _STRATEGY_FIELDS for k in updates)
        strat_s = await get_or_create_strategy_settings(session, u) if need_strat else None

        for key, value in updates.items():
            if key in _USER_FIELDS:
                setattr(u, key, value)
            elif key in _STRATEGY_FIELDS and strat_s is not None:
                setattr(strat_s, _STRATEGY_MAP[key], value)
            elif key in _ENUM_FIELDS and s:
                enum_cls = _ENUM_FIELDS[key]
                try: setattr(s, key, enum_cls(value))
                except ValueError: raise HTTPException(400, f"{key} invalide")
            elif s and hasattr(s, key):
                setattr(s, key, value)

        await session.commit()
    return {"ok": True, "updated": list(updates.keys())}


@router.post("/settings/scoring-profile")
async def apply_scoring_profile(body: ScoringProfileReq, user: User = Depends(get_current_user)):
    profile = body.profile.lower()
    if profile not in SCORING_PROFILES:
        raise HTTPException(400, "Profile invalide (prudent|balanced|aggressive)")
    preset = SCORING_PROFILES[profile]
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s: raise HTTPException(500, "User settings missing")
        for k, v in preset.items():
            if hasattr(s, k):
                setattr(s, k, v)
        await session.commit()
    return {"ok": True, "profile": profile, "applied": list(preset.keys())}


# ─────────────────────────────────────────────────────────────────
# ANALYTICS V3
# ─────────────────────────────────────────────────────────────────
@router.get("/analytics/traders")
async def analytics_traders(user: User = Depends(get_current_user)):
    """Stats détaillées par trader suivi: win rate, streaks, PnL, catégories fortes/faibles."""
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        wallets = (u.settings.followed_wallets or []) if u.settings else []
        traders = []
        for w in wallets:
            wl = w.lower()
            cutoff = datetime.utcnow() - timedelta(days=30)
            trades = (await session.execute(select(Trade).where(
                Trade.user_id == user.id, Trade.master_wallet == wl,
                Trade.status == TradeStatus.FILLED,
                Trade.created_at >= cutoff).order_by(Trade.created_at.desc()))).scalars().all()
            total = len(trades)
            settled = [t for t in trades if t.is_settled and t.settlement_pnl is not None]
            wins = sum(1 for t in settled if t.settlement_pnl > 0)
            losses = sum(1 for t in settled if t.settlement_pnl <= 0)
            pnl = sum(t.settlement_pnl for t in settled)

            # Streak
            streak = 0; streak_type = None
            for t in settled[:20]:
                is_win = t.settlement_pnl > 0
                if streak_type is None:
                    streak_type = is_win; streak = 1
                elif is_win == streak_type: streak += 1
                else: break
            resolved = wins + losses
            wr = (wins / resolved * 100) if resolved else 0

            # Categorization
            if wr >= 60 and total >= 10: category = "hot"
            elif wr <= 40 and total >= 10: category = "cold"
            elif total >= 5: category = "warm"
            else: category = "new"

            # Categories fortes / faibles (par market category/preffix si dispo)
            # On utilise market_question/market_id pour inférer une catégorie basique
            cat_perf: dict[str, list[float]] = {}
            for t in settled:
                q = (t.market_question or t.market_id or "").lower()
                for tag in ("crypto", "politics", "sports", "elections", "nfl", "nba",
                            "soccer", "football", "tennis", "boxing", "mma", "tech",
                            "pop", "science", "culture", "weather", "economy"):
                    if tag in q:
                        cat_perf.setdefault(tag.capitalize(), []).append(float(t.settlement_pnl or 0))
                        break
                else:
                    cat_perf.setdefault("Autre", []).append(float(t.settlement_pnl or 0))
            cat_stats = []
            for cat, pnls in cat_perf.items():
                w_c = sum(1 for p in pnls if p > 0)
                total_c = len(pnls)
                cat_stats.append({
                    "category": cat,
                    "trades": total_c,
                    "win_rate": round(w_c / total_c * 100, 1) if total_c else 0,
                    "pnl": round(sum(pnls), 2),
                })
            cat_stats.sort(key=lambda x: x["pnl"], reverse=True)
            strong = [c for c in cat_stats if c["win_rate"] >= 60 and c["trades"] >= 3][:3]
            weak = [c for c in cat_stats if c["win_rate"] <= 40 and c["trades"] >= 3][:3]

            traders.append({
                "wallet": w, "wallet_short": f"{w[:6]}...{w[-4:]}",
                "total_trades_30d": total,
                "wins": wins, "losses": losses,
                "win_rate": round(wr, 1),
                "pnl_30d": round(pnl, 2),
                "current_streak": streak,
                "streak_type": "win" if streak_type else ("loss" if streak_type is False else None),
                "category": category,
                "strong_categories": strong,
                "weak_categories": weak,
            })
        traders.sort(key=lambda t: t["pnl_30d"], reverse=True)
    return {"traders": traders}


@router.get("/analytics/portfolio")
async def analytics_portfolio(user: User = Depends(get_current_user)):
    """Vue portfolio: positions, exposition, PnL non réalisé, répartition."""
    async with async_session() as session:
        open_trades = (await session.execute(select(Trade).where(
            Trade.user_id == user.id, Trade.side == TradeSide.BUY,
            Trade.status == TradeStatus.FILLED, Trade.is_settled == False  # noqa: E712
        ).order_by(Trade.created_at.desc()))).scalars().all()

    total_open_value = sum(t.net_amount_usdc or 0 for t in open_trades)
    # Breakdown by wallet (source)
    by_wallet: dict[str, float] = {}
    for t in open_trades:
        w = t.master_wallet or "strategy"
        by_wallet[w] = by_wallet.get(w, 0) + (t.net_amount_usdc or 0)

    return {
        "open_count": len(open_trades),
        "total_open_value": round(total_open_value, 2),
        "by_source": [
            {"source": k, "value": round(v, 2), "pct": round(v / total_open_value * 100, 1) if total_open_value else 0}
            for k, v in sorted(by_wallet.items(), key=lambda x: -x[1])
        ],
        "positions": [{
            "market_question": t.market_question or (t.market_id or "")[:40],
            "amount": round(t.net_amount_usdc or 0, 2),
            "price": round(t.price or 0, 4),
            "shares": round(t.shares or 0, 4),
            "source": t.master_wallet[:10] + "..." if t.master_wallet else "strategy",
            "age_hours": round((datetime.utcnow() - t.created_at).total_seconds() / 3600, 1) if t.created_at else 0,
        } for t in open_trades[:50]],
    }


@router.get("/analytics/signals")
async def analytics_signals(user: User = Depends(get_current_user)):
    """Résumé de l'activité de signaux (trades exécutés récemment)."""
    async with async_session() as session:
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent = (await session.execute(select(Trade).where(
            Trade.user_id == user.id, Trade.status == TradeStatus.FILLED,
            Trade.created_at >= cutoff).order_by(Trade.created_at.desc()))).scalars().all()
    by_day: dict[str, int] = {}
    for t in recent:
        if t.created_at:
            day = t.created_at.strftime("%Y-%m-%d")
            by_day[day] = by_day.get(day, 0) + 1
    return {
        "total_7d": len(recent),
        "by_day": [{"date": d, "count": c} for d, c in sorted(by_day.items())],
        "avg_per_day": round(len(recent) / 7, 1),
    }


@router.get("/analytics/filters")
async def analytics_filters(user: User = Depends(get_current_user)):
    """Efficacité du smart filter: trades exécutés vs settings de filtres."""
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        cutoff = datetime.utcnow() - timedelta(days=30)
        total = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id, Trade.status == TradeStatus.FILLED,
            Trade.created_at >= cutoff)) or 0
    return {
        "smart_filter_enabled": s.smart_filter_enabled if s else False,
        "signal_scoring_enabled": s.signal_scoring_enabled if s else False,
        "min_signal_score": s.min_signal_score if s else 40,
        "skip_coin_flip": s.skip_coin_flip if s else True,
        "scoring_criteria": s.scoring_criteria if s and s.scoring_criteria else None,
        "trades_executed_30d": total,
    }


# ─────────────────────────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────────────────────────
async def _collect_report_data(user_id: int, period: str):
    now = datetime.utcnow()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0); period_label = "Aujourd'hui"
    elif period == "month":
        start = now - timedelta(days=30); period_label = "30 derniers jours"
    else:
        start = now - timedelta(days=7); period_label = "7 derniers jours"

    async with async_session() as session:
        trades = (await session.execute(select(Trade).where(
            Trade.user_id == user_id, Trade.status == TradeStatus.FILLED,
            Trade.created_at >= start).order_by(Trade.created_at.desc()))).scalars().all()
    settled = [t for t in trades if t.is_settled and t.settlement_pnl is not None]
    strat = [t for t in trades if t.strategy_id is not None and getattr(t, "pnl", None) is not None]
    copy_pnl = sum(t.settlement_pnl for t in settled if t.strategy_id is None)
    strat_pnl = sum(t.pnl for t in strat)
    wins = sum(1 for t in settled if t.settlement_pnl > 0) + sum(1 for t in strat if t.pnl > 0)
    losses = sum(1 for t in settled if t.settlement_pnl <= 0) + sum(1 for t in strat if t.pnl <= 0)
    resolved = wins + losses
    best = max((t.settlement_pnl for t in settled), default=0)
    worst = min((t.settlement_pnl for t in settled), default=0)
    return {
        "period": period, "period_label": period_label,
        "generated_at": now.isoformat(),
        "start": start.isoformat(),
        "pnl": round(copy_pnl + strat_pnl, 2),
        "copy_pnl": round(copy_pnl, 2),
        "strategy_pnl": round(strat_pnl, 2),
        "trades": len(trades), "wins": wins, "losses": losses,
        "win_rate": round(wins / resolved * 100, 1) if resolved else 0,
        "best_trade": round(best, 2), "worst_trade": round(worst, 2),
        "trades_list": [{
            "date": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
            "market": (t.market_question or t.market_id or "")[:60],
            "side": t.side.value.upper() if t.side else "",
            "price": round(t.price or 0, 4),
            "amount": round(t.net_amount_usdc or 0, 2),
            "pnl": round(t.settlement_pnl, 2) if t.settlement_pnl is not None else (round(t.pnl, 2) if getattr(t, "pnl", None) is not None else None),
            "source": "strategy" if t.strategy_id else ("copy" if t.master_wallet else "manual"),
        } for t in trades[:100]],
    }


@router.get("/reports/pnl")
async def report_pnl(period: str = "week", user: User = Depends(get_current_user)):
    d = await _collect_report_data(user.id, period)
    return {k: v for k, v in d.items() if k != "trades_list"}


@router.get("/reports/by-trader")
async def report_by_trader(user: User = Depends(get_current_user)):
    async with async_session() as session:
        rows = (await session.execute(select(
            Trade.master_wallet,
            func.count(Trade.id).label("trade_count"),
            func.sum(Trade.gross_amount_usdc).label("volume"),
            func.sum(Trade.settlement_pnl).label("pnl"),
        ).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.status == TradeStatus.FILLED, Trade.master_wallet.isnot(None)
        ).group_by(Trade.master_wallet))).all()  # noqa: E711
    data = [{
        "wallet": r.master_wallet,
        "wallet_short": f"{r.master_wallet[:6]}...{r.master_wallet[-4:]}",
        "trade_count": r.trade_count or 0,
        "volume": round(r.volume or 0, 2),
        "pnl": round(r.pnl or 0, 2),
    } for r in rows]
    data.sort(key=lambda x: x["pnl"], reverse=True)
    return {"traders": data}


@router.get("/reports/by-market")
async def report_by_market(user: User = Depends(get_current_user)):
    async with async_session() as session:
        rows = (await session.execute(select(
            Trade.market_id, Trade.market_question,
            func.count(Trade.id).label("trade_count"),
            func.sum(Trade.gross_amount_usdc).label("volume"),
            func.sum(Trade.settlement_pnl).label("pnl"),
        ).where(
            Trade.user_id == user.id, Trade.status == TradeStatus.FILLED
        ).group_by(Trade.market_id, Trade.market_question))).all()
    data = [{
        "market_id": r.market_id,
        "market_question": r.market_question or (r.market_id or "")[:40],
        "trade_count": r.trade_count or 0,
        "volume": round(r.volume or 0, 2),
        "pnl": round(r.pnl or 0, 2),
    } for r in rows]
    data.sort(key=lambda x: x["pnl"], reverse=True)
    return {"markets": data[:50]}


# HTML report - supports auth via Authorization header OR ?auth= query param
@router.get("/reports/export.html", response_class=HTMLResponse)
async def report_export_html(
    request: Request,
    period: str = "week",
    auth: Optional[str] = None,
):
    init_data: Optional[str] = None
    hdr = request.headers.get("Authorization", "")
    if hdr.startswith("tma "):
        init_data = hdr[4:]
    if not init_data and auth:
        try: init_data = urllib.parse.unquote(auth)
        except Exception: pass
    if not init_data:
        return HTMLResponse("<h1>Auth requise</h1>", status_code=401)
    tg_user_data = validate_init_data(init_data)
    if not tg_user_data:
        return HTMLResponse("<h1>Auth invalide</h1>", status_code=401)
    async with async_session() as session:
        u = (await session.execute(
            select(User).where(User.telegram_id == int(tg_user_data.get("id")))
        )).scalar_one_or_none()
    if not u:
        return HTMLResponse("<h1>User introuvable</h1>", status_code=404)
    user = u

    d = await _collect_report_data(user.id, period)

    # Compute trader breakdown directly
    async with async_session() as session:
        tr_rows = (await session.execute(select(
            Trade.master_wallet,
            func.count(Trade.id).label("trade_count"),
            func.sum(Trade.gross_amount_usdc).label("volume"),
            func.sum(Trade.settlement_pnl).label("pnl"),
        ).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.status == TradeStatus.FILLED, Trade.master_wallet.isnot(None)
        ).group_by(Trade.master_wallet))).all()  # noqa: E711
        mk_rows = (await session.execute(select(
            Trade.market_id, Trade.market_question,
            func.count(Trade.id).label("trade_count"),
            func.sum(Trade.gross_amount_usdc).label("volume"),
            func.sum(Trade.settlement_pnl).label("pnl"),
        ).where(
            Trade.user_id == user.id, Trade.status == TradeStatus.FILLED
        ).group_by(Trade.market_id, Trade.market_question))).all()

    by_trader = sorted([{
        "wallet": r.master_wallet,
        "wallet_short": f"{r.master_wallet[:6]}...{r.master_wallet[-4:]}",
        "trade_count": r.trade_count or 0,
        "volume": round(r.volume or 0, 2),
        "pnl": round(r.pnl or 0, 2),
    } for r in tr_rows], key=lambda x: x["pnl"], reverse=True)
    by_market = sorted([{
        "market_id": r.market_id,
        "market_question": r.market_question or (r.market_id or "")[:40],
        "trade_count": r.trade_count or 0,
        "volume": round(r.volume or 0, 2),
        "pnl": round(r.pnl or 0, 2),
    } for r in mk_rows], key=lambda x: x["pnl"], reverse=True)

    def pnl_color(x): return "#34c759" if x > 0 else ("#ff3b30" if x < 0 else "#8e8e93")
    def sign(x): return f"{'+' if x >= 0 else ''}{x:.2f}"

    trades_rows = "".join([f"""
      <tr>
        <td>{t['date']}</td>
        <td>{(t['market'] or '')[:50]}</td>
        <td><span class="badge {t['side'].lower()}">{t['side']}</span></td>
        <td>${t['price']:.4f}</td>
        <td>${t['amount']:.2f}</td>
        <td style="color:{pnl_color(t['pnl']) if t['pnl'] is not None else '#8e8e93'};font-weight:600">
          {sign(t['pnl']) if t['pnl'] is not None else '—'}
        </td>
        <td>{t['source']}</td>
      </tr>""" for t in d["trades_list"]])

    traders_rows = "".join([f"""
      <tr>
        <td>{t['wallet_short']}</td>
        <td>{t['trade_count']}</td>
        <td>${t['volume']:.2f}</td>
        <td style="color:{pnl_color(t['pnl'])};font-weight:600">{sign(t['pnl'])}</td>
      </tr>""" for t in by_trader[:20]])

    markets_rows = "".join([f"""
      <tr>
        <td>{(m['market_question'] or '')[:60]}</td>
        <td>{m['trade_count']}</td>
        <td>${m['volume']:.2f}</td>
        <td style="color:{pnl_color(m['pnl'])};font-weight:600">{sign(m['pnl'])}</td>
      </tr>""" for m in by_market[:20]])

    html = f"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rapport {d['period_label']} — WENPOLYMARKET</title>
<style>
  @page {{ size: A4; margin: 1.5cm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 24px; background: #fff; color: #1c1c1e;
    line-height: 1.5;
  }}
  .container {{ max-width: 820px; margin: 0 auto; }}
  header {{ border-bottom: 2px solid #000; padding-bottom: 16px; margin-bottom: 24px; }}
  h1 {{ margin: 0 0 4px; font-size: 24px; }}
  .meta {{ color: #666; font-size: 13px; }}
  .hero {{
    background: linear-gradient(135deg, #f8f9fb 0%, #e3f0ff 100%);
    padding: 24px; border-radius: 12px; margin-bottom: 24px; text-align: center;
  }}
  .hero-value {{ font-size: 48px; font-weight: 700; letter-spacing: -1px; }}
  .hero-label {{ text-transform: uppercase; letter-spacing: 1px; font-size: 11px; color: #666; margin-top: 4px; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
  .stat {{
    background: #f2f2f7; padding: 16px 12px; border-radius: 10px; text-align: center;
  }}
  .stat-value {{ font-size: 20px; font-weight: 700; }}
  .stat-label {{ font-size: 10px; text-transform: uppercase; color: #666; letter-spacing: 0.6px; margin-top: 2px; }}
  h2 {{ font-size: 16px; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #ddd; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 16px; }}
  th {{
    text-align: left; padding: 8px; background: #f2f2f7; font-weight: 600;
    border-bottom: 1px solid #ddd; font-size: 11px; text-transform: uppercase;
  }}
  td {{ padding: 8px; border-bottom: 1px solid #eee; }}
  .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }}
  .badge.buy {{ background: #d4f5dd; color: #1d7a32; }}
  .badge.sell {{ background: #fde0e0; color: #b3261e; }}
  footer {{
    margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd;
    color: #666; font-size: 11px; text-align: center;
  }}
  @media print {{
    body {{ padding: 0; }}
    .no-print {{ display: none; }}
  }}
  .btn {{
    display: inline-block; background: #007aff; color: white; padding: 10px 18px;
    border-radius: 8px; text-decoration: none; font-weight: 600; margin: 4px;
    border: none; cursor: pointer; font-size: 14px;
  }}
</style>
</head><body>
<div class="container">
  <div class="no-print" style="text-align:center;margin-bottom:16px">
    <button class="btn" onclick="window.print()">🖨 Imprimer / Sauver PDF</button>
    <a class="btn" href="javascript:history.back()" style="background:#666">Retour</a>
  </div>

  <header>
    <h1>Rapport WENPOLYMARKET</h1>
    <div class="meta">{d['period_label']} · Généré le {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</div>
  </header>

  <div class="hero">
    <div class="hero-value" style="color:{pnl_color(d['pnl'])}">{sign(d['pnl'])} USDC</div>
    <div class="hero-label">PnL Total — {d['period_label']}</div>
  </div>

  <div class="stats">
    <div class="stat"><div class="stat-value">{d['trades']}</div><div class="stat-label">Trades</div></div>
    <div class="stat"><div class="stat-value">{d['win_rate']}%</div><div class="stat-label">Win rate</div></div>
    <div class="stat"><div class="stat-value" style="color:{pnl_color(d['best_trade'])}">{sign(d['best_trade'])}</div><div class="stat-label">Best</div></div>
    <div class="stat"><div class="stat-value" style="color:{pnl_color(d['worst_trade'])}">{sign(d['worst_trade'])}</div><div class="stat-label">Worst</div></div>
  </div>

  <div class="stats" style="grid-template-columns:repeat(3,1fr)">
    <div class="stat"><div class="stat-value" style="color:{pnl_color(d['copy_pnl'])}">{sign(d['copy_pnl'])}</div><div class="stat-label">PnL Copy</div></div>
    <div class="stat"><div class="stat-value" style="color:{pnl_color(d['strategy_pnl'])}">{sign(d['strategy_pnl'])}</div><div class="stat-label">PnL Strategy</div></div>
    <div class="stat"><div class="stat-value">{d['wins']}/{d['losses']}</div><div class="stat-label">W / L</div></div>
  </div>

  <h2>Performance par trader</h2>
  <table>
    <thead><tr><th>Trader</th><th>Trades</th><th>Volume</th><th>PnL</th></tr></thead>
    <tbody>{traders_rows or '<tr><td colspan="4" style="text-align:center;color:#999;padding:16px">Aucune donnée</td></tr>'}</tbody>
  </table>

  <h2>Performance par marché (top 20)</h2>
  <table>
    <thead><tr><th>Marché</th><th>Trades</th><th>Volume</th><th>PnL</th></tr></thead>
    <tbody>{markets_rows or '<tr><td colspan="4" style="text-align:center;color:#999;padding:16px">Aucune donnée</td></tr>'}</tbody>
  </table>

  <h2>Détail des trades (100 derniers)</h2>
  <table>
    <thead><tr><th>Date</th><th>Marché</th><th>Side</th><th>Prix</th><th>Montant</th><th>PnL</th><th>Source</th></tr></thead>
    <tbody>{trades_rows or '<tr><td colspan="7" style="text-align:center;color:#999;padding:16px">Aucun trade</td></tr>'}</tbody>
  </table>

  <footer>
    Rapport généré automatiquement par WENPOLYMARKET. Les données reflètent l'activité du compte
    <code>{user.telegram_username or user.telegram_id}</code>.
  </footer>
</div>
</body></html>"""
    return HTMLResponse(content=html)


# ─────────────────────────────────────────────────────────────────
# USER MODE — Paper / Live switch (with double-confirm for live)
# ─────────────────────────────────────────────────────────────────
@router.post("/user/mode")
async def user_mode(body: ModeChangeReq, user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        if body.paper_trading:
            # Switch to PAPER — safe, no confirmation
            u.paper_trading = True
            u.live_mode_confirmed = False
            logger.info(f"User {user.id} switched to PAPER mode")
        else:
            # Switch to LIVE — requires explicit confirmation
            if not body.confirm_live:
                raise HTTPException(400, "Confirmation explicite requise pour passer en mode Live")
            if not u.wallet_address or not u.encrypted_private_key:
                raise HTTPException(400, "Configurez d'abord un wallet pour passer en Live")
            u.paper_trading = False
            u.live_mode_confirmed = True
            logger.warning(f"⚠ User {user.id} switched to LIVE mode")
        await session.commit()
    return {"ok": True, "paper_trading": u.paper_trading, "live_mode_confirmed": u.live_mode_confirmed}


# ─────────────────────────────────────────────────────────────────
# DISCOVER — Top traders (Polymarket leaderboard)
# ─────────────────────────────────────────────────────────────────
@router.get("/discover/top-traders")
async def discover_top_traders(
    period: str = "month",  # day | week | month | all
    limit: int = 20,
    user: User = Depends(get_current_user),
):
    """Top traders du leaderboard Polymarket.

    Période: day / week / month / all. Retourne adresse, volume, PnL si dispo.
    """
    # Polymarket data-api leaderboard endpoint
    # https://lb-api.polymarket.com/profit
    traders: list[dict] = []
    err: Optional[str] = None
    base_url = "https://lb-api.polymarket.com/profit"
    params = {"window": period if period in ("day","week","month","all") else "month", "limit": min(limit, 50)}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(base_url, params=params)
            if r.status_code == 200:
                data = r.json()
                # Try multiple response shapes (Polymarket API has changed over time)
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    for key in ("users", "data", "items", "leaderboard", "results"):
                        if key in data and isinstance(data[key], list):
                            items = data[key]; break
                for t in items[:limit]:
                    if not isinstance(t, dict):
                        continue
                    addr = (t.get("proxyWallet") or t.get("walletAddress") or t.get("address")
                            or t.get("user") or t.get("wallet") or "").lower().strip()
                    if not addr or not addr.startswith("0x") or len(addr) != 42:
                        continue
                    traders.append({
                        "wallet": addr,
                        "wallet_short": f"{addr[:6]}...{addr[-4:]}",
                        "username": t.get("name") or t.get("username") or t.get("displayName") or "",
                        "pnl": round(float(t.get("profit") or t.get("pnl") or t.get("pnlUsd") or 0), 2),
                        "volume": round(float(t.get("volume") or t.get("volumeUsd") or 0), 2),
                        "trades_count": int(t.get("trades") or t.get("numTrades") or t.get("tradesCount") or 0),
                        "profile_image": t.get("profileImage") or t.get("avatar") or "",
                    })
                if not traders:
                    err = "Polymarket a répondu mais le format n'est pas reconnu — réessayez plus tard"
            else:
                err = f"Polymarket renvoie {r.status_code}"
    except httpx.TimeoutException:
        err = "Timeout — Polymarket trop lent"
    except Exception as e:
        logger.warning(f"discover_top_traders failed: {e}")
        err = "Erreur de connexion à Polymarket"

    # Mark which ones user already follows
    followed = set()
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        if u.settings and u.settings.followed_wallets:
            followed = {w.lower() for w in u.settings.followed_wallets}
    for t in traders:
        t["followed"] = t["wallet"] in followed

    return {"traders": traders, "period": params["window"], "error": err}


@router.get("/discover/trader/{wallet}/markets")
async def discover_trader_markets(wallet: str, user: User = Depends(get_current_user)):
    """Marchés récents d'un trader (positions ouvertes sur Polymarket)."""
    wallet = wallet.lower().strip()
    if not _is_valid_address(wallet):
        raise HTTPException(400, "Adresse invalide")
    markets: list[dict] = []
    err: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://data-api.polymarket.com/positions",
                                 params={"user": wallet, "limit": 25, "sortBy": "CURRENT", "sortDirection": "DESC"})
            if r.status_code == 200:
                data = r.json()
                items = data if isinstance(data, list) else []
                for p in items[:25]:
                    markets.append({
                        "market_question": p.get("title") or p.get("question") or "",
                        "outcome": p.get("outcome") or "",
                        "size": float(p.get("size") or 0),
                        "entry_price": float(p.get("avgPrice") or 0),
                        "current_price": float(p.get("curPrice") or 0),
                        "pnl": round(float(p.get("realizedPnl") or 0) + float(p.get("cashPnl") or 0), 2),
                        "initial_value": round(float(p.get("initialValue") or 0), 2),
                        "current_value": round(float(p.get("currentValue") or 0), 2),
                    })
            else:
                err = f"API {r.status_code}"
    except Exception as e:
        logger.warning(f"discover_trader_markets failed: {e}")
        err = str(e)
    return {"wallet": wallet, "markets": markets, "error": err}


# ─────────────────────────────────────────────────────────────────
# TRADER FILTERS — Exclure des catégories pour un trader donné
# ─────────────────────────────────────────────────────────────────
@router.get("/settings/trader-filters")
async def get_trader_filters(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
    return {
        "trader_filters": (s.trader_filters or {}) if s else {},
        "global_categories": (s.categories or []) if s else [],
        "global_blacklist": (s.blacklisted_markets or []) if s else [],
    }


@router.post("/settings/trader-filter")
async def set_trader_filter(body: TraderFilterReq, user: User = Depends(get_current_user)):
    w = body.wallet.strip().lower()
    if not _is_valid_address(w):
        raise HTTPException(400, "Adresse invalide")
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s: raise HTTPException(500, "Settings manquants")
        filters = dict(s.trader_filters or {})
        if body.excluded_categories:
            filters[w] = {"excluded_categories": list(body.excluded_categories)}
        else:
            filters.pop(w, None)
        s.trader_filters = filters
        await session.commit()
    return {"ok": True, "trader_filters": filters}

