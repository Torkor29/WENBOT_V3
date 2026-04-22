"""Telegram Mini App — FastAPI router with all API endpoints."""

import asyncio
import json as _json
import logging
import re as _re
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
# All fields wired to backend services (verified 2026-04).
class SettingsUpdate(BaseModel):
    paper_trading: Optional[bool] = None
    is_paused: Optional[bool] = None
    is_active: Optional[bool] = None
    daily_limit_usdc: Optional[float] = None
    # Capital & sizing
    allocated_capital: Optional[float] = None
    sizing_mode: Optional[str] = None
    fixed_amount: Optional[float] = None
    percent_per_trade: Optional[float] = None
    multiplier: Optional[float] = None
    min_trade_usdc: Optional[float] = None
    max_trade_usdc: Optional[float] = None
    # Risk basic
    stop_loss_enabled: Optional[bool] = None
    stop_loss_pct: Optional[float] = None
    take_profit_enabled: Optional[bool] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_enabled: Optional[bool] = None
    trailing_stop_pct: Optional[float] = None
    # Risk advanced exits (cabled in position_manager.py)
    time_exit_enabled: Optional[bool] = None
    time_exit_hours: Optional[int] = None
    scale_out_enabled: Optional[bool] = None
    scale_out_pct: Optional[float] = None
    # Copy behaviour
    copy_delay_seconds: Optional[int] = None
    manual_confirmation: Optional[bool] = None
    confirmation_threshold_usdc: Optional[float] = None
    # Gas
    gas_mode: Optional[str] = None
    # Filters
    categories: Optional[list] = None
    blacklisted_markets: Optional[list] = None
    max_expiry_days: Optional[int] = None
    trader_filters: Optional[dict] = None
    # Portfolio risk
    max_positions: Optional[int] = None
    max_category_exposure_pct: Optional[float] = None
    max_direction_bias_pct: Optional[float] = None
    # Trader tracking (cabled in copytrade.py)
    auto_pause_cold_traders: Optional[bool] = None
    cold_trader_threshold: Optional[float] = None
    hot_streak_boost: Optional[float] = None
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
    # Notifications (cabled in copytrade.py + position_manager.py)
    notification_mode: Optional[str] = None
    notify_on_buy: Optional[bool] = None
    notify_on_sell: Optional[bool] = None
    notify_on_sl_tp: Optional[bool] = None
    # Strategy bucket
    strategy_trade_fee_rate: Optional[float] = None
    strategy_max_trades_per_day: Optional[int] = None
    strategy_is_paused: Optional[bool] = None
    # Permissive mode + idempotency + same-cat (anti-bloqueurs)
    permissive_mode: Optional[bool] = None
    idempotency_window_seconds: Optional[int] = None
    max_same_category_positions: Optional[int] = None


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

class BlacklistReq(BaseModel):
    market_id: str
    market_question: Optional[str] = None


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
# DIAGNOSTIC — "Pourquoi le bot ne copie-t-il rien ?"
# ─────────────────────────────────────────────────────────────────
@router.get("/diagnostic/copy-status")
async def diagnostic_copy_status(user: User = Depends(get_current_user)):
    """Scanne TOUS les bloqueurs potentiels de copie et renvoie un rapport.

    Chaque check renvoie :
      - status : "ok" | "warning" | "blocker"
      - message : explication courte
      - fix_action : (optionnel) clé d'un setting à toggler / endpoint
    """
    from sqlalchemy import select as _sel, func as _func
    from datetime import date as _date
    from bot.models.trade import Trade as _Trade, TradeStatus as _TS

    checks: list[dict] = []
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s:
            return {"checks": [{"status": "blocker", "label": "Settings", "message": "Aucun UserSettings — re-créez via /start"}]}

        # 1. Bot global
        if not u.is_active:
            checks.append({"status": "blocker", "label": "Bot", "message": "Bot désactivé (is_active=False)", "fix": "POST /controls/resume"})
        elif u.is_paused:
            checks.append({"status": "blocker", "label": "Bot", "message": "Bot en pause", "fix": "POST /controls/resume"})
        else:
            checks.append({"status": "ok", "label": "Bot", "message": "Actif & non en pause"})

        # 2. Wallet
        if not u.wallet_address or not u.encrypted_private_key:
            checks.append({"status": "blocker", "label": "Wallet", "message": "Aucun wallet configuré", "fix": "POST /wallet/create"})
        else:
            checks.append({"status": "ok", "label": "Wallet", "message": f"{u.wallet_address[:8]}…{u.wallet_address[-4:]}"})

        # 3. Mode paper/live
        if not u.paper_trading and not getattr(u, "live_mode_confirmed", False):
            checks.append({"status": "blocker", "label": "Mode Live", "message": "paper_trading=False mais live_mode_confirmed=False — bascule silencieuse en paper à chaque trade", "fix": "POST /user/mode {paper_trading:false, confirm_live:true}"})
        else:
            checks.append({"status": "ok", "label": "Mode", "message": "Paper" if u.paper_trading else "LIVE confirmé"})

        # 4. Followed wallets
        followed = (s.followed_wallets or [])
        if len(followed) == 0:
            checks.append({"status": "blocker", "label": "Traders suivis", "message": "Aucun wallet suivi", "fix": "POST /copy/traders/add"})
        else:
            checks.append({"status": "ok", "label": "Traders suivis", "message": f"{len(followed)} wallet(s)"})

        # 5. Mode permissif (+ check migration DB)
        if not hasattr(s, "permissive_mode"):
            checks.append({
                "status": "blocker",
                "label": "Migration DB",
                "message": "Colonne `permissive_mode` absente — la migration n'a pas tourné. Restart le bot (docker compose restart bot).",
                "fix": "docker compose restart bot",
            })
            permissive = False
        else:
            permissive = bool(getattr(s, "permissive_mode", False))
            checks.append({
                "status": "ok" if permissive else "warning",
                "label": "Mode permissif",
                "message": "🔓 ACTIF — tous filtres bypassés" if permissive else "OFF — filtres ci-dessous appliqués",
                "fix": None if permissive else "POST /settings {permissive_mode:true}",
            })

        # 6. Filtres bloquants (uniquement si permissive=False)
        if not permissive:
            if s.signal_scoring_enabled and (s.min_signal_score or 0) > 0:
                checks.append({"status": "warning", "label": "Signal scoring", "message": f"ON — score min {s.min_signal_score:.0f}/100 (rejette coin flips ~30)", "fix": "POST /settings {signal_scoring_enabled:false}"})
            if s.smart_filter_enabled:
                checks.append({"status": "warning", "label": "Smart filter", "message": f"ON — skip_coin_flip={s.skip_coin_flip}, min_winrate={s.min_trader_winrate_for_type:.0f}%", "fix": "POST /settings {smart_filter_enabled:false}"})
            if s.auto_pause_cold_traders:
                checks.append({"status": "warning", "label": "Cold trader pause", "message": f"ON — bloque traders < {s.cold_trader_threshold:.0f}% WR sur 7j (rejette coin flippers)", "fix": "POST /settings {auto_pause_cold_traders:false}"})
            if (s.max_positions or 15) <= 15:
                checks.append({"status": "warning", "label": "Max positions", "message": f"Max {s.max_positions} positions ouvertes — peut bloquer si plein"})
            if (getattr(s, "max_same_category_positions", 3) or 3) <= 3:
                checks.append({"status": "warning", "label": "Max same-category", "message": f"Max {getattr(s, 'max_same_category_positions', 3)} positions/catégorie — bloque BTC 5m répétés"})
            if s.manual_confirmation:
                checks.append({"status": "warning", "label": "Manual confirmation", "message": "ON — chaque trade attend confirmation Telegram"})
        else:
            checks.append({"status": "ok", "label": "Filtres", "message": "Tous bypassés (mode permissif)"})

        # 7. Idempotency window
        idem = getattr(s, "idempotency_window_seconds", 60) or 60
        if idem >= 300:
            checks.append({"status": "warning", "label": "Anti-replay", "message": f"Fenêtre {idem}s — bloque les re-trades sur marchés courts (BTC 5m)", "fix": "POST /settings {idempotency_window_seconds:60}"})
        else:
            checks.append({"status": "ok", "label": "Anti-replay", "message": f"{idem}s — ok pour BTC 5m"})

        # 8. Daily limit
        today = _date.today()
        daily_spent = await session.scalar(
            _sel(_func.sum(_Trade.gross_amount_usdc)).where(
                _Trade.user_id == u.id,
                _Trade.side == TradeSide.BUY,
                _Trade.status == _TS.FILLED,
                _func.date(_Trade.created_at) == today,
            )
        ) or 0.0
        if daily_spent >= (s.daily_limit_usdc or 0):
            checks.append({"status": "blocker", "label": "Daily limit", "message": f"${daily_spent:.0f} dépensé / ${s.daily_limit_usdc:.0f} limite — atteinte", "fix": "POST /settings {daily_limit_usdc:5000}"})
        else:
            checks.append({"status": "ok", "label": "Daily limit", "message": f"${daily_spent:.0f} / ${s.daily_limit_usdc:.0f}"})

        # 9. Sizing
        if s.fixed_amount > (s.confirmation_threshold_usdc or 50) and s.manual_confirmation:
            checks.append({"status": "warning", "label": "Sizing vs confirm", "message": f"fixed={s.fixed_amount}$ > seuil confirm {s.confirmation_threshold_usdc}$ → confirmation manuelle requise"})
        if s.min_trade_usdc < 1.0:
            checks.append({"status": "blocker", "label": "Min trade", "message": f"min_trade_usdc={s.min_trade_usdc}$ < 1$ (Polymarket exige $1 min)", "fix": "POST /settings {min_trade_usdc:1.0}"})

        # 10. USDC balance live
        if not u.paper_trading and u.wallet_address:
            try:
                bal = await web3_client.get_usdc_balance(u.wallet_address)
                if bal < s.min_trade_usdc:
                    checks.append({"status": "blocker", "label": "USDC", "message": f"Solde {bal:.2f}$ < min_trade {s.min_trade_usdc:.2f}$"})
                else:
                    checks.append({"status": "ok", "label": "USDC", "message": f"{bal:.2f}$"})
                matic = await web3_client.get_matic_balance(u.wallet_address)
                if matic < 0.01:
                    checks.append({"status": "blocker", "label": "MATIC gas", "message": f"{matic:.4f} MATIC — insuffisant pour gas"})
                else:
                    checks.append({"status": "ok", "label": "MATIC", "message": f"{matic:.4f}"})
            except Exception as e:
                checks.append({"status": "warning", "label": "Balances", "message": f"Erreur fetch: {e}"})

    # Synthèse
    blockers = [c for c in checks if c["status"] == "blocker"]
    warnings = [c for c in checks if c["status"] == "warning"]
    summary = (
        f"❌ {len(blockers)} bloqueur(s) trouvé(s) — corrigez-les en priorité"
        if blockers
        else f"✅ Aucun bloqueur. {len(warnings)} avertissement(s) (filtres actifs qui peuvent rejeter)"
        if warnings
        else "✅ Tout est vert — la copie devrait fonctionner"
    )
    return {"summary": summary, "blockers_count": len(blockers), "warnings_count": len(warnings), "checks": checks}


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
    """Open positions with LIVE current price + unrealized PnL.

    Joins Trade (entry data) with ActivePosition (current price tracked by
    position_manager every 15s).
    """
    from bot.models.active_position import ActivePosition

    async with async_session() as session:
        # Open BUY trades
        trade_rows = (await session.execute(select(Trade).where(
            Trade.user_id == user.id, Trade.strategy_id.is_(None),
            Trade.side == TradeSide.BUY, Trade.status == TradeStatus.FILLED,
            Trade.is_settled == False).order_by(Trade.created_at.desc()).limit(50))).scalars().all()

        # Active positions (live current_price)
        ap_rows = (await session.execute(select(ActivePosition).where(
            ActivePosition.user_id == user.id,
            ActivePosition.is_closed == False,  # noqa: E712
        ))).scalars().all()
        ap_by_token = {p.token_id: p for p in ap_rows if p.token_id}

    positions = []
    total_unrealized = 0.0
    for t in trade_rows:
        ap = ap_by_token.get(t.token_id) if t.token_id else None
        entry_price = float(t.price or 0)
        current_price = float(ap.current_price) if ap and ap.current_price else entry_price
        shares = float(t.shares or 0)
        if not shares and entry_price > 0:
            shares = float(t.net_amount_usdc or 0) / entry_price
        invested = float(t.net_amount_usdc or 0)
        current_value = shares * current_price if current_price > 0 else invested
        unrealized_pnl = current_value - invested
        unrealized_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        total_unrealized += unrealized_pnl
        positions.append({
            "trade_id": t.trade_id,
            "market_question": t.market_question or (t.market_id or "")[:40],
            "entry_price": round(entry_price, 4),
            "current_price": round(current_price, 4),
            "shares": round(shares, 4),
            "invested": round(invested, 2),
            "current_value": round(current_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pct": round(unrealized_pct, 1),
            "master_wallet": f"{t.master_wallet[:6]}...{t.master_wallet[-4:]}" if t.master_wallet else "",
            "master_wallet_full": t.master_wallet or "",
            "is_paper": t.is_paper,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "executed_at": t.executed_at.isoformat() if t.executed_at else None,
            "execution_time_ms": int(t.execution_time_ms) if t.execution_time_ms else None,
            "live": ap is not None,  # True si position_manager track le prix
        })

    return {
        "positions": positions,
        "count": len(positions),
        "total_invested": round(sum(p["invested"] for p in positions), 2),
        "total_current_value": round(sum(p["current_value"] for p in positions), 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "last_update": datetime.utcnow().isoformat(),
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
            "executed_at": t.executed_at.isoformat() if t.executed_at else None,
            "execution_time_ms": int(t.execution_time_ms) if t.execution_time_ms else None,
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

    # 🔧 CRITICAL: Notify the monitor immediately — without this, the bot
    # waits up to 60s for the next scheduled refresh, missing trades in between.
    try:
        from bot.services import _registry as _svc_reg
        if _svc_reg.monitor is not None:
            await _svc_reg.monitor.refresh_watched_wallets()
            logger.info(f"Monitor refreshed after trader add: {w_lower[:10]}...")
    except Exception as e:
        logger.warning(f"Could not refresh monitor after add: {e}")

    return {
        "ok": True,
        "count": len(wallets),
        "message": "Trader ajouté. Le bot commencera à copier ses PROCHAINS trades.",
        "note": "Les trades que ce trader a déjà ouverts ne sont pas rétro-copiés (seules les nouvelles positions déclenchent une copie).",
    }


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


@router.post("/strategy-wallet/withdraw")
async def strat_wallet_withdraw(body: WithdrawReq, user: User = Depends(get_current_user)):
    addr = getattr(user, "strategy_wallet_address", None)
    pk_enc = getattr(user, "encrypted_strategy_private_key", None)
    if not addr or not pk_enc:
        raise HTTPException(404, "No strategy wallet")
    if body.amount <= 0: raise HTTPException(400, "Montant invalide")
    if not _is_valid_address(body.to_address):
        raise HTTPException(400, "Adresse destination invalide")
    try: pk = decrypt_private_key(pk_enc, cfg.encryption_key, user.uuid)
    except Exception: raise HTTPException(500, "Impossible de déchiffrer la clé")
    try:
        result = await web3_client.transfer_usdc(
            from_address=addr, to_address=body.to_address,
            amount_usdc=body.amount, private_key=pk,
        )
    except Exception as e:
        logger.error(f"strategy withdraw failed for user {user.id}: {e}")
        raise HTTPException(500, f"Transaction échouée: {e}")
    if not getattr(result, "success", False):
        raise HTTPException(500, getattr(result, "error", None) or "Transaction échouée")
    tx_hash = getattr(result, "tx_hash", None) or ""
    logger.info(f"User {user.id} STRATEGY withdrew {body.amount} USDC to {body.to_address}")
    return {"tx_hash": tx_hash}


@router.post("/strategy-wallet/export-pk")
async def strat_wallet_export_pk(body: ExportPkReq, user: User = Depends(get_current_user)):
    if not body.confirm: raise HTTPException(400, "Confirmation requise")
    pk_enc = getattr(user, "encrypted_strategy_private_key", None)
    if not pk_enc: raise HTTPException(404, "No strategy wallet")
    try: pk = decrypt_private_key(pk_enc, cfg.encryption_key, user.uuid)
    except Exception: raise HTTPException(500, "Impossible de déchiffrer la clé")
    logger.warning(f"⚠ User {user.id} exported STRATEGY private key via miniapp")
    return {"private_key": pk}


# ─────────────────────────────────────────────────────────────────
# REDEEM — Positions résolues à réclamer manuellement sur Polymarket
# (le redeem on-chain auto n'est pas câblé — fournit liens directs)
# ─────────────────────────────────────────────────────────────────
@router.get("/positions/redeemable")
async def positions_redeemable(user: User = Depends(get_current_user)):
    """Positions résolues GAGNANTES où l'utilisateur peut réclamer ses USDC.

    Retourne les trades :
      - LIVE (pas paper)
      - side BUY (vous avez acheté un outcome)
      - is_settled=True (le marché s'est résolu)
      - settlement_pnl > 0 (vous avez gagné)

    Note : le redeem on-chain auto (appel redeemPositions sur le contrat
    Conditional Tokens Polygon) n'est pas câblé. L'utilisateur clique le
    lien Polymarket pour réclamer ses USDC en 2 clics.
    """
    if not user.wallet_address:
        return {
            "items": [], "count": 0, "total_expected_usdc": 0,
            "wallet_address": None, "polymarket_portfolio_url": None,
            "error": "Aucun wallet configuré",
        }

    async with async_session() as session:
        winners = (await session.execute(
            select(Trade).where(
                Trade.user_id == user.id,
                Trade.side == TradeSide.BUY,
                Trade.is_settled == True,  # noqa: E712
                Trade.settlement_pnl.isnot(None),
                Trade.settlement_pnl > 0,
                Trade.is_paper == False,  # noqa: E712 — only live winners need on-chain redeem
            ).order_by(Trade.resolved_at.desc().nullslast(), Trade.created_at.desc()).limit(50)
        )).scalars().all()

    items = []
    for t in winners:
        # Calculate shares (fallback to net_amount/price if shares is null)
        shares = t.shares
        if not shares and t.price and t.price > 0:
            shares = (t.net_amount_usdc or 0) / t.price
        shares = float(shares or 0)
        # On Polymarket, each winning share pays out exactly 1 USDC
        expected_payout = shares * 1.0
        items.append({
            "trade_id": t.trade_id,
            "market_question": t.market_question or (t.market_id or "")[:60],
            "market_id": t.market_id or "",
            "shares": round(shares, 4),
            "invested": round(t.net_amount_usdc or 0, 2),
            "expected_payout": round(expected_payout, 2),
            "pnl": round(t.settlement_pnl or 0, 2),
            "outcome": t.market_outcome or "?",
            "resolved_at": (t.resolved_at.isoformat() if getattr(t, "resolved_at", None) else None),
            "settled_at": (t.created_at.isoformat() if t.created_at else None),
        })

    total_to_redeem = sum(i["expected_payout"] for i in items)
    return {
        "items": items,
        "count": len(items),
        "total_expected_usdc": round(total_to_redeem, 2),
        "wallet_address": user.wallet_address,
        "polymarket_portfolio_url": f"https://polymarket.com/profile/{user.wallet_address}",
    }


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
            "time_exit_enabled", "time_exit_hours",
            "scale_out_enabled", "scale_out_pct",
            # copy
            "copy_delay_seconds", "manual_confirmation", "confirmation_threshold_usdc",
            # gas
            "gas_mode",
            # filters
            "categories", "blacklisted_markets", "max_expiry_days", "trader_filters",
            # portfolio
            "max_positions", "max_category_exposure_pct", "max_direction_bias_pct",
            # trader tracking
            "auto_pause_cold_traders", "cold_trader_threshold", "hot_streak_boost",
            # scoring / smart
            "signal_scoring_enabled", "min_signal_score", "scoring_criteria",
            "smart_filter_enabled", "min_trader_winrate_for_type", "min_trader_trades_for_type",
            "skip_coin_flip", "min_conviction_pct", "max_price_drift_pct",
            # notifs
            "notification_mode", "notify_on_buy", "notify_on_sell", "notify_on_sl_tp",
            # followed
            "followed_wallets",
            # permissive mode + idempotency + same-cat (anti-bloqueurs)
            "permissive_mode", "idempotency_window_seconds", "max_same_category_positions",
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


# Default values — keep in sync with bot/models/settings.py defaults
_SETTINGS_DEFAULTS = {
    # UserSettings
    "allocated_capital": 100.0,
    "sizing_mode": "fixed",
    "fixed_amount": 10.0,
    "percent_per_trade": 5.0,
    "multiplier": 1.0,
    "min_trade_usdc": 1.0,
    "max_trade_usdc": 100.0,
    "stop_loss_enabled": True,
    "stop_loss_pct": 20.0,
    "take_profit_enabled": False,
    "take_profit_pct": 50.0,
    "trailing_stop_enabled": False,
    "trailing_stop_pct": 10.0,
    "time_exit_enabled": False,
    "time_exit_hours": 24,
    "scale_out_enabled": False,
    "scale_out_pct": 50.0,
    "copy_delay_seconds": 0,
    "manual_confirmation": False,
    "confirmation_threshold_usdc": 50.0,
    "gas_mode": "fast",
    "max_expiry_days": None,
    "max_positions": 15,
    "max_category_exposure_pct": 30.0,
    "max_direction_bias_pct": 70.0,
    "auto_pause_cold_traders": True,
    "cold_trader_threshold": 40.0,
    "hot_streak_boost": 1.5,
    "signal_scoring_enabled": True,
    "min_signal_score": 40.0,
    "smart_filter_enabled": True,
    "min_trader_winrate_for_type": 55.0,
    "min_trader_trades_for_type": 10,
    "skip_coin_flip": True,
    "min_conviction_pct": 2.0,
    "max_price_drift_pct": 5.0,
    "notification_mode": "dm",
    "notify_on_buy": True,
    "notify_on_sell": True,
    "notify_on_sl_tp": True,
    # User flags
    "is_paused": False,
    "daily_limit_usdc": 1000.0,
    # Strategy
    "strategy_trade_fee_rate": 0.01,
    "strategy_max_trades_per_day": 50,
    "strategy_is_paused": False,
}


@router.post("/settings/reset-defaults")
async def reset_settings_defaults(user: User = Depends(get_current_user)):
    """Réinitialise tous les paramètres aux valeurs par défaut recommandées.

    Ne touche PAS à :
    - paper_trading / live_mode_confirmed (safety)
    - wallet_address / private keys
    - followed_wallets / trader_filters / blacklisted_markets (choix user)
    - scoring_criteria (utilisez /settings/scoring-profile pour reset)
    """
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s:
            raise HTTPException(500, "User settings missing")

        applied = []
        for key, default_val in _SETTINGS_DEFAULTS.items():
            # Dispatch per target (User / UserSettings / StrategyUserSettings)
            if key == "is_paused":
                u.is_paused = default_val
                applied.append(key)
            elif key == "daily_limit_usdc":
                u.daily_limit_usdc = default_val
                applied.append(key)
            elif key.startswith("strategy_"):
                strat_s = await get_or_create_strategy_settings(session, u)
                strat_map = {
                    "strategy_trade_fee_rate": "trade_fee_rate",
                    "strategy_max_trades_per_day": "max_trades_per_day",
                    "strategy_is_paused": "is_paused",
                }
                attr = strat_map.get(key)
                if attr and hasattr(strat_s, attr):
                    setattr(strat_s, attr, default_val)
                    applied.append(key)
            elif key in ("sizing_mode", "gas_mode"):
                enum_cls = _ENUM_FIELDS.get(key)
                if enum_cls:
                    try: setattr(s, key, enum_cls(default_val))
                    except Exception: pass
                    applied.append(key)
            elif hasattr(s, key):
                setattr(s, key, default_val)
                applied.append(key)

        await session.commit()
    logger.info(f"User {user.id} reset settings to defaults ({len(applied)} fields)")
    return {"ok": True, "reset_count": len(applied), "fields": applied}


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
    """Top traders du leaderboard Polymarket. Robuste — n'échoue jamais en 500.

    Période: day / week / month / all. Retourne adresse, volume, PnL si dispo.
    """
    try:
        return await _do_discover_top_traders(period, limit, user)
    except Exception as e:
        logger.error(f"discover_top_traders crashed: {e}", exc_info=True)
        return {
            "traders": [],
            "period": period,
            "error": f"Erreur interne: {type(e).__name__} — {str(e)[:200]}",
        }


_LB_TRADER_RE = _re.compile(
    r'\{"rank":\d+,"proxyWallet":"0x[a-fA-F0-9]{40}"[^{}]*?"amount":[\d.\-eE+]+[^{}]*?\}'
)
_LB_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}


async def _scrape_polymarket_leaderboard(poly_period: str, limit: int) -> tuple[list, Optional[str]]:
    """Scrape https://polymarket.com/leaderboard/overall/{poly_period}/profit
    pour récupérer les vrais classements par période (l'API publique ne supporte
    pas les périodes — seul le frontend SSR a les bonnes données).

    poly_period in ('today', 'weekly', 'monthly', 'all')
    """
    url = f"https://polymarket.com/leaderboard/overall/{poly_period}/profit"
    items: list = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(url, headers=_LB_BROWSER_HEADERS)
            if r.status_code != 200:
                return [], f"Polymarket leaderboard {r.status_code}"
            html = r.text
            # Extract all trader objects from the SSR HTML
            for match in _LB_TRADER_RE.finditer(html):
                if len(items) >= limit:
                    break
                raw = match.group(0)
                try:
                    obj = _json.loads(raw)
                except Exception:
                    continue
                addr = str(obj.get("proxyWallet") or "").lower().strip()
                if not addr.startswith("0x") or len(addr) != 42:
                    continue
                items.append({
                    "wallet": addr,
                    "wallet_short": f"{addr[:6]}...{addr[-4:]}",
                    "username": str(obj.get("pseudonym") or obj.get("name") or ""),
                    "pnl": round(float(obj.get("amount") or 0), 2),
                    "volume": round(float(obj.get("volume") or 0), 2),
                    "trades_count": 0,
                    "profile_image": str(obj.get("profileImageOptimized") or obj.get("profileImage") or ""),
                })
            if not items:
                return [], "Aucun trader extrait du HTML Polymarket"
            return items, None
    except httpx.TimeoutException:
        return [], "Polymarket trop lent à répondre"
    except Exception as e:
        logger.warning(f"_scrape_polymarket_leaderboard {url} failed: {e}")
        return [], f"Erreur scraping: {type(e).__name__}"


async def _do_discover_top_traders(period: str, limit: int, user: User) -> dict:
    traders: list = []
    err: Optional[str] = None
    # Map period to Polymarket frontend URL slug
    period_map = {"day": "today", "week": "weekly", "month": "monthly", "all": "all"}
    poly_period = period_map.get(period, "monthly")

    # Scrape la page leaderboard SSR de Polymarket pour obtenir le classement
    # par période (l'API publique /profit ignore le param de période).
    traders, err = await _scrape_polymarket_leaderboard(poly_period, min(limit, 50))

    # Mark which ones user already follows (defensive)
    try:
        followed: set = set()
        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
            if u and u.settings and u.settings.followed_wallets:
                followed = {str(w).lower() for w in u.settings.followed_wallets if w}
        for t in traders:
            t["followed"] = t["wallet"] in followed
    except Exception as e:
        logger.warning(f"discover followed check failed: {e}")
        for t in traders:
            t.setdefault("followed", False)

    return {"traders": traders, "period": period, "count": len(traders), "error": err}


@router.get("/discover/trader/{wallet}/markets")
async def discover_trader_markets(wallet: str, user: User = Depends(get_current_user)):
    """Marchés récents d'un trader (positions ouvertes sur Polymarket).

    Trié par activité la plus récente DESC — on fetch en parallèle positions + trades
    récents, on mappe les timestamps par conditionId et on trie par `last_activity_ts`.
    """
    wallet = wallet.lower().strip()
    if not _is_valid_address(wallet):
        raise HTTPException(400, "Adresse invalide")
    markets: list[dict] = []
    err: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            # Parallèle : positions (état courant) + activity (timestamps)
            pos_task = client.get(
                "https://data-api.polymarket.com/positions",
                params={"user": wallet, "limit": 25, "sortBy": "CURRENT", "sortDirection": "DESC"},
            )
            act_task = client.get(
                "https://data-api.polymarket.com/activity",
                params={"user": wallet, "limit": 200, "type": "TRADE"},
            )
            r_pos, r_act = await asyncio.gather(pos_task, act_task, return_exceptions=True)

            # Map conditionId → timestamp le plus récent (secondes)
            last_ts: dict[str, int] = {}
            if not isinstance(r_act, Exception) and getattr(r_act, "status_code", 0) == 200:
                try:
                    acts = r_act.json() or []
                    for a in acts if isinstance(acts, list) else []:
                        cid = (a.get("conditionId") or "").lower()
                        if not cid:
                            continue
                        raw_ts = int(a.get("timestamp") or 0)
                        # Normaliser : ms → s
                        ts = raw_ts // 1000 if raw_ts > 1_000_000_000_000 else raw_ts
                        if ts > last_ts.get(cid, 0):
                            last_ts[cid] = ts
                except Exception:
                    pass

            if isinstance(r_pos, Exception):
                err = str(r_pos)
            elif r_pos.status_code == 200:
                data = r_pos.json()
                items = data if isinstance(data, list) else []
                for p in items[:25]:
                    cid = (p.get("conditionId") or "").lower()
                    markets.append({
                        "market_id": cid,  # sert d'ID de blocage
                        "condition_id": cid,
                        "market_question": p.get("title") or p.get("question") or "",
                        "outcome": p.get("outcome") or "",
                        "size": float(p.get("size") or 0),
                        "entry_price": float(p.get("avgPrice") or 0),
                        "current_price": float(p.get("curPrice") or 0),
                        "pnl": round(float(p.get("realizedPnl") or 0) + float(p.get("cashPnl") or 0), 2),
                        "initial_value": round(float(p.get("initialValue") or 0), 2),
                        "current_value": round(float(p.get("currentValue") or 0), 2),
                        "last_activity_ts": last_ts.get(cid, 0),
                    })
                # Tri : activité la plus récente en haut (fallback sur current_value pour les marchés sans activité)
                markets.sort(key=lambda m: (m["last_activity_ts"], m["current_value"]), reverse=True)
            else:
                err = f"API {r_pos.status_code}"
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


# ─────────────────────────────────────────────────────────────────
# BLACKLIST DE MARCHÉS — par utilisateur, global à tous ses traders
# ─────────────────────────────────────────────────────────────────
@router.get("/copy/blacklist")
async def blacklist_get(user: User = Depends(get_current_user)):
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        bl = (s.blacklisted_markets or []) if s else []
    return {"blacklist": bl, "count": len(bl)}


@router.post("/copy/blacklist/add")
async def blacklist_add(body: BlacklistReq, user: User = Depends(get_current_user)):
    mkt = (body.market_id or "").strip().lower()
    if not mkt:
        raise HTTPException(400, "market_id requis")
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s: raise HTTPException(500, "Settings manquants")
        bl = list(s.blacklisted_markets or [])
        if mkt not in [m.lower() for m in bl]:
            bl.append(mkt)
        s.blacklisted_markets = bl
        await session.commit()
    return {"ok": True, "blacklist": bl, "count": len(bl)}


@router.delete("/copy/blacklist/{market_id:path}")
async def blacklist_remove(market_id: str, user: User = Depends(get_current_user)):
    mkt = (market_id or "").strip().lower()
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        s = u.settings
        if not s: raise HTTPException(500, "Settings manquants")
        bl = [m for m in (s.blacklisted_markets or []) if m.lower() != mkt]
        s.blacklisted_markets = bl
        await session.commit()
    return {"ok": True, "blacklist": bl, "count": len(bl)}


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


# ─────────────────────────────────────────────────────────────────
# NOTIFICATIONS FEED (Mini App)
# Derived from trades + active_positions closed events.
# Unread tracking via users.last_notif_seen_at.
# ─────────────────────────────────────────────────────────────────
def _trade_to_notif(t: Trade) -> dict:
    side = (t.side.value if t.side else "").upper()
    is_strat = bool(t.strategy_id)
    icon = "🟢" if side == "BUY" else ("🔴" if side == "SELL" else "📊")
    title = f"{icon} {side} {'(stratégie)' if is_strat else ''}".strip()
    market = t.market_question or (t.market_id or "")[:40]
    body_parts = []
    if t.shares: body_parts.append(f"{t.shares:.2f} shares @ {t.price:.4f}")
    if t.net_amount_usdc: body_parts.append(f"{t.net_amount_usdc:.2f} USDC")
    if t.master_wallet: body_parts.append(f"via {t.master_wallet[:6]}…{t.master_wallet[-4:]}")
    severity = "info"
    if t.settlement_pnl is not None:
        severity = "success" if t.settlement_pnl > 0 else ("error" if t.settlement_pnl < 0 else "info")
        body_parts.append(f"PnL {'+' if t.settlement_pnl >= 0 else ''}{t.settlement_pnl:.2f}")
    return {
        "id": f"trade_{t.id}",
        "kind": ("strategy_trade" if is_strat else f"copy_{side.lower()}"),
        "title": title,
        "market": market,
        "body": " · ".join(body_parts) if body_parts else "",
        "severity": severity,
        "is_paper": t.is_paper,
        "trade_id": t.trade_id,
        "created_at": (t.created_at.isoformat() if t.created_at else None),
        "ts": (t.created_at.timestamp() if t.created_at else 0),
    }


def _exit_to_notif(p) -> dict:
    """active_position closed → notif."""
    reason = (getattr(p, "close_reason", "") or "").lower()
    icon_map = {
        "sl_hit": "🛑", "tp_hit": "🎯", "trailing_stop": "📉",
        "time_exit": "⏱", "scale_out": "✂️",
    }
    label_map = {
        "sl_hit": "Stop Loss déclenché",
        "tp_hit": "Take Profit atteint",
        "trailing_stop": "Trailing stop sortie",
        "time_exit": "Sortie temporelle",
        "scale_out": "Take Profit partiel",
    }
    icon = icon_map.get(reason, "📤")
    title = f"{icon} {label_map.get(reason, 'Position fermée')}"
    market = getattr(p, "market_question", None) or (getattr(p, "market_id", "") or "")[:40]
    pnl_pct = getattr(p, "pnl_pct", None) or 0
    body_parts = []
    body_parts.append(f"Entry {p.entry_price:.4f} → {p.current_price:.4f}")
    if pnl_pct: body_parts.append(f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%")
    body_parts.append(f"{p.shares:.2f} sh")
    severity = "success" if pnl_pct > 0 else ("error" if pnl_pct < 0 else "warning")
    if reason == "sl_hit": severity = "error"
    elif reason in ("tp_hit", "scale_out"): severity = "success"
    return {
        "id": f"exit_{p.id}",
        "kind": "exit_" + (reason or "unknown"),
        "title": title,
        "market": market,
        "body": " · ".join(body_parts),
        "severity": severity,
        "is_paper": False,
        "trade_id": None,
        "created_at": (p.closed_at.isoformat() if p.closed_at else None),
        "ts": (p.closed_at.timestamp() if p.closed_at else 0),
    }


@router.get("/notifications")
async def notifications_list(
    limit: int = 50,
    kind: Optional[str] = None,  # all | trades | exits
    user: User = Depends(get_current_user),
):
    """Timeline of recent events for this user (trades + position exits)."""
    from bot.models.active_position import ActivePosition
    items: list[dict] = []
    cutoff = datetime.utcnow() - timedelta(days=30)

    async with async_session() as session:
        if kind in (None, "all", "trades"):
            trades = (await session.execute(
                select(Trade).where(
                    Trade.user_id == user.id,
                    Trade.status == TradeStatus.FILLED,
                    Trade.created_at >= cutoff,
                ).order_by(Trade.created_at.desc()).limit(min(limit, 100))
            )).scalars().all()
            items.extend(_trade_to_notif(t) for t in trades)

        if kind in (None, "all", "exits"):
            exits = (await session.execute(
                select(ActivePosition).where(
                    ActivePosition.user_id == user.id,
                    ActivePosition.is_closed == True,  # noqa: E712
                    ActivePosition.closed_at.isnot(None),
                    ActivePosition.closed_at >= cutoff,
                ).order_by(ActivePosition.closed_at.desc()).limit(min(limit, 100))
            )).scalars().all()
            items.extend(_exit_to_notif(p) for p in exits)

    items.sort(key=lambda x: x["ts"], reverse=True)
    items = items[:min(limit, 100)]

    last_seen = getattr(user, "last_notif_seen_at", None)
    last_seen_ts = last_seen.timestamp() if last_seen else 0
    for it in items:
        it["unread"] = it["ts"] > last_seen_ts

    return {"items": items, "count": len(items), "last_seen": last_seen.isoformat() if last_seen else None}


@router.get("/notifications/unread-count")
async def notifications_unread_count(user: User = Depends(get_current_user)):
    """Fast count of unread notifications (events after last_notif_seen_at)."""
    from bot.models.active_position import ActivePosition
    last_seen = getattr(user, "last_notif_seen_at", None) or datetime(1970, 1, 1)
    async with async_session() as session:
        n_trades = await session.scalar(select(func.count(Trade.id)).where(
            Trade.user_id == user.id,
            Trade.status == TradeStatus.FILLED,
            Trade.created_at > last_seen,
        )) or 0
        n_exits = await session.scalar(select(func.count(ActivePosition.id)).where(
            ActivePosition.user_id == user.id,
            ActivePosition.is_closed == True,  # noqa: E712
            ActivePosition.closed_at.isnot(None),
            ActivePosition.closed_at > last_seen,
        )) or 0
    return {"unread": int(n_trades) + int(n_exits)}


@router.post("/notifications/mark-read")
async def notifications_mark_read(user: User = Depends(get_current_user)):
    """Marks all current notifications as read."""
    async with async_session() as session:
        u = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        u.last_notif_seen_at = datetime.utcnow()
        await session.commit()
    return {"ok": True, "last_seen": u.last_notif_seen_at.isoformat()}

