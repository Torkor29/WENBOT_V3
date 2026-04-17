"""Telegram Mini App — FastAPI router with all API endpoints."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from eth_account import Account
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from web3 import Web3

from bot.config import settings as cfg
from bot.db.session import async_session
from bot.models.user import User
from bot.models.trade import Trade, TradeStatus, TradeSide
from bot.models.settings import UserSettings
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
class SettingsUpdate(BaseModel):
    paper_trading: Optional[bool] = None
    is_paused: Optional[bool] = None
    daily_limit_usdc: Optional[float] = None
    sizing_mode: Optional[str] = None
    fixed_amount: Optional[float] = None
    proportional_pct: Optional[float] = None
    max_trade_usdc: Optional[float] = None
    min_trade_usdc: Optional[float] = None
    stop_loss_enabled: Optional[bool] = None
    stop_loss_pct: Optional[float] = None
    take_profit_enabled: Optional[bool] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_enabled: Optional[bool] = None
    trailing_stop_pct: Optional[float] = None
    smart_filter_enabled: Optional[bool] = None
    min_signal_score: Optional[float] = None
    min_volume_24h: Optional[float] = None
    min_liquidity: Optional[float] = None
    max_spread_pct: Optional[float] = None
    notify_on_buy: Optional[bool] = None
    notify_on_sell: Optional[bool] = None
    notify_on_sl_tp: Optional[bool] = None
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
        settings_rel = u.settings
        followed_count = len(settings_rel.followed_wallets) if settings_rel and settings_rel.followed_wallets else 0

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
        "paper_balance": round(u.paper_balance, 2) if u.paper_balance else 0,
        "daily_limit_usdc": u.daily_limit_usdc,
        "daily_spent_usdc": round(u.daily_spent_usdc, 2) if u.daily_spent_usdc else 0,
        "followed_wallets_count": followed_count,
        "active_subscriptions": sub_count,
        "created_at": u.created_at.isoformat() if u.created_at else None,
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
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
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
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        u.wallet_auto_created = False
        await save_wallet(session, u, acct.address, pk, "polygon")
    logger.info(f"User {user.id} imported wallet {acct.address}")
    return {"address": acct.address}


@router.get("/wallet/balance")
async def wallet_balance(user: User = Depends(get_current_user)):
    if not user.wallet_address:
        raise HTTPException(404, "No wallet configured")
    try:
        usdc = await web3_client.get_usdc_balance(user.wallet_address)
    except Exception as e:
        logger.warning(f"get_usdc_balance failed: {e}")
        usdc = 0.0
    try:
        matic = await web3_client.get_matic_balance(user.wallet_address)
    except Exception as e:
        logger.warning(f"get_matic_balance failed: {e}")
        matic = 0.0
    return {
        "address": user.wallet_address,
        "usdc": round(float(usdc), 4),
        "matic": round(float(matic), 6),
    }


@router.post("/wallet/withdraw")
async def wallet_withdraw(body: WithdrawReq, user: User = Depends(get_current_user)):
    if not user.wallet_address or not user.encrypted_private_key:
        raise HTTPException(404, "No wallet")
    if body.amount <= 0:
        raise HTTPException(400, "Montant invalide")
    if not _is_valid_address(body.to_address):
        raise HTTPException(400, "Adresse destination invalide")
    try:
        pk = decrypt_private_key(user.encrypted_private_key, cfg.encryption_key, user.uuid)
    except Exception:
        raise HTTPException(500, "Impossible de déchiffrer la clé")
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
    if not body.confirm:
        raise HTTPException(400, "Confirmation requise")
    if not user.encrypted_private_key:
        raise HTTPException(404, "No wallet")
    try:
        pk = decrypt_private_key(user.encrypted_private_key, cfg.encryption_key, user.uuid)
    except Exception:
        raise HTTPException(500, "Impossible de déchiffrer la clé")
    logger.warning(f"⚠ User {user.id} exported private key via miniapp")
    return {"private_key": pk}


@router.delete("/wallet")
async def wallet_delete(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        u.wallet_address = None
        u.encrypted_private_key = None
        u.wallet_auto_created = False
        await session.commit()
    logger.info(f"User {user.id} removed wallet")
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────
# COPY — stats, positions, history
# ─────────────────────────────────────────────────────────────────
@router.get("/copy/stats")
async def get_copy_stats(user: User = Depends(get_current_user)):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    async with async_session() as session:
        total = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0
        today = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
                Trade.created_at >= today_start,
            )
        ) or 0
        volume = await session.scalar(
            select(func.sum(Trade.gross_amount_usdc)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0.0
        total_pnl = await session.scalar(
            select(func.sum(Trade.settlement_pnl)).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.is_settled == True,  # noqa: E712
                Trade.settlement_pnl != None,  # noqa: E711
            )
        ) or 0.0
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


@router.get("/copy/positions")
async def get_copy_positions(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
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
                "market_question": t.market_question or (t.market_id or "")[:40],
                "price": round(t.price or 0, 4),
                "amount": round(t.net_amount_usdc or 0, 2),
                "shares": round(t.shares or 0, 4),
                "master_wallet": f"{t.master_wallet[:6]}...{t.master_wallet[-4:]}" if t.master_wallet else "",
                "master_wallet_full": t.master_wallet or "",
                "is_paper": t.is_paper,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in trades
        ],
        "count": len(trades),
    }


@router.get("/copy/trades")
async def get_copy_trades(limit: int = 20, offset: int = 0, user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            ).order_by(Trade.created_at.desc()).limit(min(limit, 50)).offset(max(offset, 0))
        )
        trades = result.scalars().all()
    return {
        "trades": [
            {
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
            }
            for t in trades
        ],
        "count": len(trades),
    }


# ─────────────────────────────────────────────────────────────────
# COPY TRADERS
# ─────────────────────────────────────────────────────────────────
@router.get("/copy/traders")
async def get_copy_traders(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        s = u.settings
        wallets = s.followed_wallets if s and s.followed_wallets else []
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
            pnl = await session.scalar(
                select(func.sum(Trade.settlement_pnl)).where(
                    Trade.user_id == user.id,
                    Trade.master_wallet == w.lower(),
                    Trade.is_settled == True,  # noqa: E712
                    Trade.settlement_pnl != None,  # noqa: E711
                )
            ) or 0.0
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
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        s = u.settings
        if not s:
            raise HTTPException(500, "User settings missing")
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
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        s = u.settings
        if not s:
            raise HTTPException(500, "User settings missing")
        wallets = [x for x in (s.followed_wallets or []) if x.lower() != w_lower]
        s.followed_wallets = wallets
        await session.commit()
    return {"ok": True, "count": len(wallets)}


@router.get("/copy/traders/{wallet}/stats")
async def trader_detail(wallet: str, user: User = Depends(get_current_user)):
    w_lower = wallet.strip().lower()
    async with async_session() as session:
        total = await session.scalar(
            select(func.count(Trade.id)).where(
                Trade.user_id == user.id,
                Trade.master_wallet == w_lower,
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0
        volume = await session.scalar(
            select(func.sum(Trade.gross_amount_usdc)).where(
                Trade.user_id == user.id,
                Trade.master_wallet == w_lower,
                Trade.status == TradeStatus.FILLED,
            )
        ) or 0.0
        pnl = await session.scalar(
            select(func.sum(Trade.settlement_pnl)).where(
                Trade.user_id == user.id,
                Trade.master_wallet == w_lower,
                Trade.is_settled == True,  # noqa: E712
                Trade.settlement_pnl != None,  # noqa: E711
            )
        ) or 0.0
        last_trades_q = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.master_wallet == w_lower,
                Trade.status == TradeStatus.FILLED,
            ).order_by(Trade.created_at.desc()).limit(10)
        )
        last_trades = last_trades_q.scalars().all()
    return {
        "wallet": wallet,
        "trade_count": total,
        "volume": round(volume, 2),
        "pnl": round(pnl, 2),
        "recent_trades": [
            {
                "market_question": t.market_question or (t.market_id or "")[:40],
                "side": t.side.value.upper() if t.side else "",
                "price": round(t.price or 0, 4),
                "amount": round(t.net_amount_usdc or 0, 2),
                "pnl": round(t.settlement_pnl, 2) if t.settlement_pnl is not None else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in last_trades
        ],
    }


# ─────────────────────────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────────────────────────
@router.get("/strategies")
async def get_strategies(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Strategy).where(
                Strategy.visibility == StrategyVisibility.PUBLIC,
                Strategy.status.in_([StrategyStatus.ACTIVE, StrategyStatus.TESTING]),
            ).order_by(Strategy.total_pnl.desc())
        )
        strategies = result.scalars().all()
        subs = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.is_active == True,  # noqa: E712
            )
        )
        active_sub_map = {s.strategy_id: s for s in subs.scalars().all()}
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
                "subscribed": s.id in active_sub_map,
                "my_trade_size": active_sub_map[s.id].trade_size if s.id in active_sub_map else None,
            }
            for s in strategies
        ],
    }


@router.get("/strategies/subscriptions")
async def get_subscriptions(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.created_at.desc())
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


@router.post("/strategies/{strategy_id}/subscribe")
async def strat_subscribe(strategy_id: str, body: SubscribeRequest, user: User = Depends(get_current_user)):
    async with async_session() as session:
        strat = await session.get(Strategy, strategy_id)
        if not strat:
            raise HTTPException(404, "Strategy not found")
        if strat.status not in (StrategyStatus.ACTIVE, StrategyStatus.TESTING):
            raise HTTPException(400, "Strategy non souscriptible")
        if not (strat.min_trade_size <= body.trade_size <= strat.max_trade_size):
            raise HTTPException(400, f"trade_size doit être entre {strat.min_trade_size} et {strat.max_trade_size}")
        existing = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.strategy_id == strategy_id,
            )
        )
        sub = existing.scalar_one_or_none()
        if sub:
            sub.trade_size = body.trade_size
            sub.is_active = True
        else:
            sub = Subscription(
                user_id=user.id,
                strategy_id=strategy_id,
                trade_size=body.trade_size,
                is_active=True,
            )
            session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return {"ok": True, "subscription_id": sub.id}


@router.post("/strategies/{strategy_id}/unsubscribe")
async def strat_unsubscribe(strategy_id: str, user: User = Depends(get_current_user)):
    async with async_session() as session:
        existing = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.strategy_id == strategy_id,
            )
        )
        sub = existing.scalar_one_or_none()
        if not sub:
            raise HTTPException(404, "Subscription introuvable")
        sub.is_active = False
        await session.commit()
    return {"ok": True}


@router.patch("/strategies/{strategy_id}/subscription")
async def strat_patch_sub(strategy_id: str, body: SubscriptionPatch, user: User = Depends(get_current_user)):
    async with async_session() as session:
        strat = await session.get(Strategy, strategy_id)
        existing = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.strategy_id == strategy_id,
            )
        )
        sub = existing.scalar_one_or_none()
        if not sub:
            raise HTTPException(404, "Subscription introuvable")
        if body.trade_size is not None:
            if strat and not (strat.min_trade_size <= body.trade_size <= strat.max_trade_size):
                raise HTTPException(400, "trade_size hors bornes")
            sub.trade_size = body.trade_size
        if body.is_active is not None:
            sub.is_active = body.is_active
        await session.commit()
    return {"ok": True}


@router.get("/strategies/trades")
async def get_strategy_trades(limit: int = 20, offset: int = 0, user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.strategy_id != None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
            ).order_by(Trade.created_at.desc()).limit(min(limit, 50)).offset(max(offset, 0))
        )
        trades = result.scalars().all()
    return {
        "trades": [
            {
                "trade_id": t.trade_id,
                "strategy_id": t.strategy_id,
                "market_question": t.market_question or (t.market_id or "")[:40],
                "side": t.side.value.upper() if t.side else "",
                "price": round(t.price or 0, 4),
                "amount": round(t.net_amount_usdc or 0, 2),
                "shares": round(t.shares or 0, 4),
                "result": getattr(t, "result", None),
                "pnl": round(t.pnl, 2) if getattr(t, "pnl", None) is not None else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in trades
        ],
    }


@router.get("/strategies/stats")
async def get_strategy_stats(user: User = Depends(get_current_user)):
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


# ─────────────────────────────────────────────────────────────────
# STRATEGY WALLET
# ─────────────────────────────────────────────────────────────────
@router.post("/strategy-wallet/create")
async def strat_wallet_create(user: User = Depends(get_current_user)):
    if getattr(user, "strategy_wallet_address", None):
        raise HTTPException(400, "Wallet stratégie déjà configuré")
    acct = Account.create()
    pk_hex = acct.key.hex()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        encrypted = encrypt_private_key(pk_hex, cfg.encryption_key, u.uuid)
        u.strategy_wallet_address = acct.address
        u.encrypted_strategy_private_key = encrypted
        u.strategy_wallet_auto_created = True
        await session.commit()
    return {"address": acct.address, "private_key": pk_hex}


@router.post("/strategy-wallet/import")
async def strat_wallet_import(body: ImportPkReq, user: User = Depends(get_current_user)):
    pk = body.private_key.strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    if len(pk) != 66:
        raise HTTPException(400, "Clé privée invalide")
    try:
        acct = Account.from_key(pk)
    except Exception:
        raise HTTPException(400, "Clé privée invalide")
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        encrypted = encrypt_private_key(pk, cfg.encryption_key, u.uuid)
        u.strategy_wallet_address = acct.address
        u.encrypted_strategy_private_key = encrypted
        u.strategy_wallet_auto_created = False
        await session.commit()
    return {"address": acct.address}


@router.get("/strategy-wallet/balance")
async def strat_wallet_balance(user: User = Depends(get_current_user)):
    addr = getattr(user, "strategy_wallet_address", None)
    if not addr:
        raise HTTPException(404, "No strategy wallet")
    try:
        usdc = await web3_client.get_usdc_balance(addr)
    except Exception:
        usdc = 0.0
    try:
        matic = await web3_client.get_matic_balance(addr)
    except Exception:
        matic = 0.0
    return {"address": addr, "usdc": round(float(usdc), 4), "matic": round(float(matic), 6)}


@router.delete("/strategy-wallet")
async def strat_wallet_delete(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        u.strategy_wallet_address = None
        u.encrypted_strategy_private_key = None
        u.strategy_wallet_auto_created = False
        await session.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────────
@router.get("/settings")
async def get_settings(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        s = u.settings
        strat_s = getattr(u, "strategy_settings", None)

    data = {
        "paper_trading": u.paper_trading,
        "is_paused": u.is_paused,
        "daily_limit_usdc": u.daily_limit_usdc,
        "daily_spent_usdc": round(u.daily_spent_usdc or 0, 2),
    }
    if s:
        for field in [
            "sizing_mode", "fixed_amount", "proportional_pct",
            "max_trade_usdc", "min_trade_usdc",
            "stop_loss_enabled", "stop_loss_pct",
            "take_profit_enabled", "take_profit_pct",
            "trailing_stop_enabled", "trailing_stop_pct",
            "smart_filter_enabled", "min_signal_score",
            "min_volume_24h", "min_liquidity", "max_spread_pct",
            "notify_on_buy", "notify_on_sell", "notify_on_sl_tp",
            "followed_wallets",
        ]:
            if hasattr(s, field):
                val = getattr(s, field)
                if hasattr(val, "value"):
                    val = val.value
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

    if "stop_loss_pct" in updates and not (0 < updates["stop_loss_pct"] <= 100):
        raise HTTPException(400, "stop_loss_pct doit être entre 0 et 100")
    if "take_profit_pct" in updates and not (0 < updates["take_profit_pct"] <= 500):
        raise HTTPException(400, "take_profit_pct doit être entre 0 et 500")
    if "trailing_stop_pct" in updates and not (0 < updates["trailing_stop_pct"] <= 100):
        raise HTTPException(400, "trailing_stop_pct doit être entre 0 et 100")
    if "min_signal_score" in updates and not (0 <= updates["min_signal_score"] <= 1):
        raise HTTPException(400, "min_signal_score doit être entre 0 et 1")
    if "strategy_trade_fee_rate" in updates and not (0.01 <= updates["strategy_trade_fee_rate"] <= 0.20):
        raise HTTPException(400, "trade_fee_rate entre 1% et 20%")
    if "strategy_max_trades_per_day" in updates and not (1 <= updates["strategy_max_trades_per_day"] <= 200):
        raise HTTPException(400, "max_trades_per_day entre 1 et 200")
    if "fixed_amount" in updates and updates["fixed_amount"] <= 0:
        raise HTTPException(400, "fixed_amount doit être > 0")

    user_fields = {"paper_trading", "is_paused", "daily_limit_usdc"}
    strategy_fields = {"strategy_trade_fee_rate", "strategy_max_trades_per_day", "strategy_is_paused"}
    strategy_map = {
        "strategy_trade_fee_rate": "trade_fee_rate",
        "strategy_max_trades_per_day": "max_trades_per_day",
        "strategy_is_paused": "is_paused",
    }

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        s = u.settings
        need_strat = any(k in strategy_fields for k in updates)
        strat_s = await get_or_create_strategy_settings(session, u) if need_strat else None

        for key, value in updates.items():
            if key in user_fields:
                setattr(u, key, value)
            elif key in strategy_fields and strat_s is not None:
                setattr(strat_s, strategy_map[key], value)
            elif s and hasattr(s, key):
                setattr(s, key, value)

        await session.commit()
    return {"ok": True, "updated": list(updates.keys())}


# ─────────────────────────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────────────────────────
@router.get("/reports/pnl")
async def report_pnl(period: str = "week", user: User = Depends(get_current_user)):
    now = datetime.utcnow()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=7)

    async with async_session() as session:
        trades_q = await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.status == TradeStatus.FILLED,
                Trade.created_at >= start,
            )
        )
        trades = trades_q.scalars().all()

    settled = [t for t in trades if t.is_settled and t.settlement_pnl is not None]
    strat_trades = [t for t in trades if t.strategy_id is not None and getattr(t, "pnl", None) is not None]

    copy_pnl = sum(t.settlement_pnl for t in settled if t.strategy_id is None)
    strat_pnl = sum(t.pnl for t in strat_trades)
    total_pnl = copy_pnl + strat_pnl

    wins = sum(1 for t in settled if t.settlement_pnl > 0) + sum(1 for t in strat_trades if t.pnl > 0)
    losses = sum(1 for t in settled if t.settlement_pnl <= 0) + sum(1 for t in strat_trades if t.pnl <= 0)
    resolved = wins + losses

    best = max((t.settlement_pnl for t in settled), default=0)
    worst = min((t.settlement_pnl for t in settled), default=0)

    return {
        "period": period,
        "pnl": round(total_pnl, 2),
        "copy_pnl": round(copy_pnl, 2),
        "strategy_pnl": round(strat_pnl, 2),
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / resolved * 100, 1) if resolved else 0,
        "best_trade": round(best, 2),
        "worst_trade": round(worst, 2),
    }


@router.get("/reports/by-trader")
async def report_by_trader(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(
                Trade.master_wallet,
                func.count(Trade.id).label("trade_count"),
                func.sum(Trade.gross_amount_usdc).label("volume"),
                func.sum(Trade.settlement_pnl).label("pnl"),
            ).where(
                Trade.user_id == user.id,
                Trade.strategy_id == None,  # noqa: E711
                Trade.status == TradeStatus.FILLED,
                Trade.master_wallet != None,  # noqa: E711
            ).group_by(Trade.master_wallet)
        )
        rows = result.all()
    data = [
        {
            "wallet": r.master_wallet,
            "wallet_short": f"{r.master_wallet[:6]}...{r.master_wallet[-4:]}",
            "trade_count": r.trade_count or 0,
            "volume": round(r.volume or 0, 2),
            "pnl": round(r.pnl or 0, 2),
        }
        for r in rows
    ]
    data.sort(key=lambda x: x["pnl"], reverse=True)
    return {"traders": data}


@router.get("/reports/by-market")
async def report_by_market(user: User = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(
                Trade.market_id,
                Trade.market_question,
                func.count(Trade.id).label("trade_count"),
                func.sum(Trade.gross_amount_usdc).label("volume"),
                func.sum(Trade.settlement_pnl).label("pnl"),
            ).where(
                Trade.user_id == user.id,
                Trade.status == TradeStatus.FILLED,
            ).group_by(Trade.market_id, Trade.market_question)
        )
        rows = result.all()
    data = [
        {
            "market_id": r.market_id,
            "market_question": r.market_question or (r.market_id or "")[:40],
            "trade_count": r.trade_count or 0,
            "volume": round(r.volume or 0, 2),
            "pnl": round(r.pnl or 0, 2),
        }
        for r in rows
    ]
    data.sort(key=lambda x: x["pnl"], reverse=True)
    return {"markets": data[:50]}
