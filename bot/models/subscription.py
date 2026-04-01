"""Subscription model — links a user to a strategy with trade settings."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Float, Boolean, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "strategy_id", name="uq_sub_user_strategy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )

    # Trade size per signal (USDC)
    trade_size: Mapped[float] = mapped_column(Float, default=4.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="subscriptions")

    def __repr__(self) -> str:
        state = "ON" if self.is_active else "OFF"
        return f"<Subscription user={self.user_id} strat={self.strategy_id} ${self.trade_size} [{state}]>"


from .user import User  # noqa: E402, F401
from .strategy import Strategy  # noqa: E402, F401
