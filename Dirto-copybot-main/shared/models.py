"""Data models matching the Supabase DB schema and Redis signal format."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, List, Optional


@dataclass
class User:
    id: str
    created_at: datetime
    telegram_id: int
    telegram_username: Optional[str]
    wallet_address: str
    encrypted_private_key: str
    trade_fee_rate: float = 0.01
    is_active: bool = True
    max_trade_size: float = 4.0
    max_trades_per_day: int = 50
    is_paused: bool = False
    matic_refills_count: int = 0
    matic_total_sent: float = 0.0
    last_matic_refill_at: Optional[datetime] = None
    trades_today: int = 0
    trades_today_reset_at: Optional[date] = None


@dataclass
class Strategy:
    id: str
    name: str
    description: Optional[str] = None
    docker_image: str = ""
    version: str = "1.0.0"
    status: str = "testing"  # active | paused | testing
    visibility: str = "private"  # public | private
    markets: List[Any] = field(default_factory=list)
    min_trade_size: float = 2.0
    max_trade_size: float = 10.0
    execution_delay_ms: int = 100
    track_record_since: Optional[datetime] = None
    total_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    created_at: Optional[datetime] = None


@dataclass
class Subscription:
    id: str
    user_id: str
    strategy_id: str
    trade_size: float
    is_active: bool = True
    created_at: Optional[datetime] = None


@dataclass
class Trade:
    id: str
    created_at: Optional[datetime] = None
    user_id: Optional[str] = None
    strategy_id: Optional[str] = None
    market_slug: str = ""
    token_id: Optional[str] = None
    direction: Optional[str] = None
    side: Optional[str] = None  # YES | NO
    entry_price: Optional[float] = None
    amount_usdc: Optional[float] = None
    trade_fee_rate: Optional[float] = None
    trade_fee_amount: Optional[float] = None
    trade_fee_tx_hash: Optional[str] = None
    order_tx_hash: Optional[str] = None
    status: str = "PENDING"  # PENDING | PLACED | FILLED | FAILED | SKIPPED
    result: Optional[str] = None  # WON | LOST
    pnl: Optional[float] = None
    execution_priority: Optional[int] = None
    execution_delay_ms: Optional[int] = None
    resolved_at: Optional[datetime] = None


@dataclass
class DailyPerformanceFee:
    id: str
    created_at: Optional[datetime] = None
    user_id: Optional[str] = None
    date: Optional[date] = None
    total_trades: Optional[int] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    total_pnl: Optional[float] = None
    perf_fee_rate: float = 0.05
    perf_fee_amount: Optional[float] = None
    perf_fee_tx_hash: Optional[str] = None
    status: str = "PENDING"  # PENDING | SENT | SKIPPED | FAILED


@dataclass
class Signal:
    """Signal format published via Redis pub/sub by strategy pods."""

    strategy_id: str
    action: str  # "BUY" / "SELL"
    side: str  # "YES" / "NO"
    market_slug: str
    token_id: str
    max_price: float
    shares: float = 0.0  # for SELL: number of shares to sell
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
