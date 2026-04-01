"""DailyPerformanceFee model — daily performance fee records for strategy users."""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Integer, Float, String, Date, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class PerfFeeStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class DailyPerformanceFee(Base):
    __tablename__ = "daily_performance_fees"
    __table_args__ = (
        UniqueConstraint("user_id", "fee_date", name="uq_perf_fee_user_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    fee_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Trade stats for the day
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    # Fee calculation
    perf_fee_rate: Mapped[float] = mapped_column(Float, default=0.05)  # 5%
    perf_fee_amount: Mapped[float] = mapped_column(Float, default=0.0)
    perf_fee_tx_hash: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    status: Mapped[PerfFeeStatus] = mapped_column(
        Enum(PerfFeeStatus), default=PerfFeeStatus.PENDING
    )

    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Relationship
    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<DailyPerformanceFee user={self.user_id} "
            f"date={self.fee_date} pnl={self.total_pnl} [{self.status.value}]>"
        )


from .user import User  # noqa: E402, F401
