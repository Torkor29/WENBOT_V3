"""StrategySignal model — audit trail for every signal received from Redis."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Float, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class StrategySignal(Base):
    __tablename__ = "strategy_signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("strategies.id"), index=True
    )

    # Signal details
    action: Mapped[str] = mapped_column(String(8))   # BUY / SELL
    side: Mapped[str] = mapped_column(String(8))      # YES / NO
    market_slug: Mapped[str] = mapped_column(String(512))
    token_id: Mapped[str] = mapped_column(String(256))
    max_price: Mapped[float] = mapped_column(Float, default=0.0)
    shares: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Execution stats (filled after dispatch)
    subscribers_count: Mapped[int] = mapped_column(Integer, default=0)
    executed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    total_volume: Mapped[float] = mapped_column(Float, default=0.0)

    # Original signal timestamp (from the strategy pod)
    signal_timestamp: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Relationship
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="signals")

    def __repr__(self) -> str:
        return (
            f"<StrategySignal {self.strategy_id} {self.action} {self.side} "
            f"slug={self.market_slug[:30]}>"
        )


from .strategy import Strategy  # noqa: E402, F401
