"""Strategy model — trading strategies that publish signals via Redis."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Float, Integer, Text, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class StrategyStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    TESTING = "testing"


class StrategyVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    docker_image: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[str] = mapped_column(String(16), default="1.0.0")

    status: Mapped[StrategyStatus] = mapped_column(
        Enum(StrategyStatus), default=StrategyStatus.TESTING
    )
    visibility: Mapped[StrategyVisibility] = mapped_column(
        Enum(StrategyVisibility), default=StrategyVisibility.PRIVATE
    )

    # Target markets (optional JSON list of market slugs)
    markets: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Trade size bounds
    min_trade_size: Mapped[float] = mapped_column(Float, default=2.0)
    max_trade_size: Mapped[float] = mapped_column(Float, default=10.0)

    # Execution delay between subscribers (ms)
    execution_delay_ms: Mapped[int] = mapped_column(Integer, default=100)

    # Aggregate performance stats (recalculated by resolver)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # Relationships
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="strategy", lazy="selectin"
    )
    signals: Mapped[list["StrategySignal"]] = relationship(
        "StrategySignal", back_populates="strategy", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Strategy {self.id} [{self.status.value}] WR={self.win_rate:.0f}%>"


from .subscription import Subscription  # noqa: E402, F401
from .strategy_signal import StrategySignal  # noqa: E402, F401
