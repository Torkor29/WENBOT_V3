"""StrategyUserSettings model — per-user settings for strategy service.

Separate from UserSettings (copy wallet) to keep the two services
fully individualized.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Integer, Float, Boolean, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class StrategyUserSettings(Base):
    __tablename__ = "strategy_user_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    # Fee rate for strategy trades (1-20%, paid on each BUY)
    trade_fee_rate: Mapped[float] = mapped_column(Float, default=0.01)

    # Daily trade limits
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=50)
    trades_today: Mapped[int] = mapped_column(Integer, default=0)
    trades_today_reset_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )

    # Pause strategy execution
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)

    # MATIC gas anti-exploit tracking
    matic_refills_count: Mapped[int] = mapped_column(Integer, default=0)
    matic_total_sent: Mapped[float] = mapped_column(Float, default=0.0)
    last_matic_refill_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="strategy_settings")

    def __repr__(self) -> str:
        state = "PAUSED" if self.is_paused else "ACTIVE"
        return (
            f"<StrategyUserSettings user={self.user_id} "
            f"fee={self.trade_fee_rate:.0%} [{state}]>"
        )


from .user import User  # noqa: E402, F401
