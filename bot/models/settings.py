"""UserSettings model — per-follower copytrade configuration."""

import enum
from typing import Optional

from sqlalchemy import (
    Integer, Float, String, Boolean, Enum, ForeignKey, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SizingMode(str, enum.Enum):
    FIXED = "fixed"               # Fixed USDC amount per trade
    PERCENT = "percent"           # % of allocated capital per trade
    PROPORTIONAL = "proportional" # Proportional to master trader size
    KELLY = "kelly"               # Kelly criterion (advanced)


class GasMode(str, enum.Enum):
    NORMAL = "normal"   # 30 gwei priority fee — standard, ~2s confirmation
    FAST = "fast"       # 50 gwei priority fee — faster, ~1-1.5s confirmation
    ULTRA = "ultra"     # 100 gwei priority fee — fastest, <1s confirmation
    INSTANT = "instant" # 200 gwei priority fee — maximum speed, costs more POL


# Priority fee in gwei for each gas mode
GAS_PRIORITY_FEES = {
    GasMode.NORMAL: 30,
    GasMode.FAST: 50,
    GasMode.ULTRA: 100,
    GasMode.INSTANT: 200,
}

# Labels for UI display
GAS_MODE_LABELS = {
    GasMode.NORMAL: "🐢 Normal (30 gwei) — ~2s",
    GasMode.FAST: "🚀 Fast (50 gwei) — ~1.5s",
    GasMode.ULTRA: "⚡ Ultra (100 gwei) — <1s",
    GasMode.INSTANT: "💎 Instant (200 gwei) — max speed",
}


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Capital
    allocated_capital: Mapped[float] = mapped_column(Float, default=100.0)
    sizing_mode: Mapped[SizingMode] = mapped_column(
        Enum(SizingMode), default=SizingMode.FIXED
    )
    fixed_amount: Mapped[float] = mapped_column(Float, default=10.0)
    percent_per_trade: Mapped[float] = mapped_column(Float, default=5.0)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    # Risk management
    stop_loss_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=20.0)
    take_profit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    take_profit_pct: Mapped[float] = mapped_column(Float, default=50.0)
    max_trade_usdc: Mapped[float] = mapped_column(Float, default=100.0)
    min_trade_usdc: Mapped[float] = mapped_column(Float, default=1.0)

    # Copy behavior
    copy_delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    manual_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_threshold_usdc: Mapped[float] = mapped_column(Float, default=50.0)

    # Bridge
    auto_bridge_sol: Mapped[bool] = mapped_column(Boolean, default=False)

    # Followed traders (list of Polygon wallet addresses to copy)
    followed_wallets: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # Filters
    categories: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    blacklisted_markets: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    max_expiry_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Per-trader category filters
    # Format: {"0xwallet": {"excluded_categories": ["Crypto/XRP", "Sports"]}, ...}
    trader_filters: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Gas priority mode — controls how fast transactions confirm on Polygon
    gas_mode: Mapped[GasMode] = mapped_column(
        Enum(GasMode), default=GasMode.FAST
    )

    # Monitor mode (master tracking)
    # Ces flags décrivent comment ce follower souhaite que les masters
    # soient suivis. Dans la pratique, pour un bot mono-admin, ils servent
    # aussi de configuration globale lisible dans l'UI.
    use_gamma_monitor: Mapped[bool] = mapped_column(Boolean, default=True)
    use_ws_monitor: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="settings")

    def __repr__(self) -> str:
        return f"<UserSettings user_id={self.user_id} mode={self.sizing_mode.value}>"


from .user import User  # noqa: E402, F401
