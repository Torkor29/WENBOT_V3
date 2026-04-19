"""FeeRecord model — audit trail for every platform fee collected."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, Float, String, ForeignKey, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, utcnow


class FeeRecord(Base):
    __tablename__ = "fee_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    trade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trades.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Fee details
    gross_amount: Mapped[float] = mapped_column(Float, nullable=False)
    fee_rate: Mapped[float] = mapped_column(Float, nullable=False)
    fee_amount: Mapped[float] = mapped_column(Float, nullable=False)
    net_amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Transfer info
    fees_wallet: Mapped[str] = mapped_column(String(255), nullable=False)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    confirmed_on_chain: Mapped[bool] = mapped_column(Boolean, default=False)

    # Paper trade flag
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="fees")
    trade: Mapped["Trade"] = relationship("Trade", back_populates="fee_record")

    def __repr__(self) -> str:
        return (
            f"<FeeRecord user={self.user_id} fee={self.fee_amount} "
            f"confirmed={self.confirmed_on_chain}>"
        )


from .user import User  # noqa: E402, F401
from .trade import Trade  # noqa: E402, F401
