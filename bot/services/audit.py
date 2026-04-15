"""Audit log service — records all user and system actions.

All actions are logged to the database for compliance and debugging.
Audit logs are never exposed via the Telegram bot — admin DB access only.
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import String, Integer, Text, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base, utcnow

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    # User actions
    USER_REGISTERED = "user_registered"
    USER_LOGIN = "user_login"
    WALLET_ADDED = "wallet_added"
    SETTINGS_CHANGED = "settings_changed"
    COPYTRADE_PAUSED = "copytrade_paused"
    COPYTRADE_RESUMED = "copytrade_resumed"
    COPYTRADE_STOPPED = "copytrade_stopped"

    # Trade actions
    TRADE_SIGNAL = "trade_signal"
    TRADE_EXECUTED = "trade_executed"
    TRADE_FAILED = "trade_failed"
    TRADE_CANCELLED = "trade_cancelled"

    # Fee actions
    FEE_CALCULATED = "fee_calculated"
    FEE_TRANSFERRED = "fee_transferred"
    FEE_TRANSFER_FAILED = "fee_transfer_failed"

    # Security actions
    RATE_LIMITED = "rate_limited"
    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"
    OTP_GENERATED = "otp_generated"
    OTP_VERIFIED = "otp_verified"
    OTP_FAILED = "otp_failed"

    # Admin actions
    ADMIN_VIEW = "admin_view"
    ADMIN_CONFIG_CHANGE = "admin_config_change"


class AuditLog(Base):
    """Audit log model — immutable record of all actions."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    trade_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    amount_usdc: Mapped[Optional[float]] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} user={self.user_id} at={self.timestamp}>"


class AuditService:
    """Service for recording audit entries."""

    async def log(
        self,
        session,
        action: AuditAction,
        user_id: Optional[int] = None,
        telegram_id: Optional[int] = None,
        details: Optional[str] = None,
        trade_id: Optional[str] = None,
        amount_usdc: Optional[float] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Record an audit log entry."""
        entry = AuditLog(
            action=action.value,
            user_id=user_id,
            telegram_id=telegram_id,
            details=details,
            trade_id=trade_id,
            amount_usdc=amount_usdc,
            ip_address=ip_address,
        )
        session.add(entry)
        # Don't commit — let the caller manage the transaction

        logger.debug(
            f"Audit: {action.value} user={user_id} "
            f"details={details[:50] if details else 'none'}"
        )

    async def get_user_logs(
        self,
        session,
        user_id: int,
        limit: int = 50,
    ) -> list[AuditLog]:
        """Get recent audit logs for a user."""
        from sqlalchemy import select

        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_action_logs(
        self,
        session,
        action: AuditAction,
        limit: int = 50,
    ) -> list[AuditLog]:
        """Get recent logs for a specific action type."""
        from sqlalchemy import select

        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.action == action.value)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# Singleton
audit_service = AuditService()
