"""Tests for audit log service."""

import os
import pytest

os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"
os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"

from bot.services.audit import AuditService, AuditAction, AuditLog


class TestAuditAction:
    def test_enum_values(self):
        assert AuditAction.USER_REGISTERED == "user_registered"
        assert AuditAction.TRADE_EXECUTED == "trade_executed"
        assert AuditAction.FEE_TRANSFERRED == "fee_transferred"
        assert AuditAction.RATE_LIMITED == "rate_limited"

    def test_all_categories_present(self):
        # Ensure we have actions for all key categories
        actions = [a.value for a in AuditAction]
        assert any("user" in a for a in actions)
        assert any("trade" in a for a in actions)
        assert any("fee" in a for a in actions)
        assert any("bridge" in a for a in actions)
        assert any("circuit" in a for a in actions)
        assert any("otp" in a for a in actions)
        assert any("admin" in a for a in actions)


class TestAuditService:
    @pytest.mark.asyncio
    async def test_log_entry(self, db_session):
        # We need to create the audit_logs table in the test DB
        from bot.models.base import Base
        from sqlalchemy import inspect

        # Check if table exists (it should since we create all tables in conftest)
        svc = AuditService()
        await svc.log(
            db_session,
            action=AuditAction.USER_REGISTERED,
            user_id=1,
            telegram_id=12345,
            details="New user registered",
        )
        await db_session.commit()

        logs = await svc.get_user_logs(db_session, user_id=1)
        assert len(logs) == 1
        assert logs[0].action == "user_registered"
        assert logs[0].telegram_id == 12345

    @pytest.mark.asyncio
    async def test_log_trade_action(self, db_session):
        svc = AuditService()
        await svc.log(
            db_session,
            action=AuditAction.TRADE_EXECUTED,
            user_id=1,
            trade_id="trade-001",
            amount_usdc=100.0,
            details="BUY YES @ 0.34",
        )
        await db_session.commit()

        logs = await svc.get_action_logs(
            db_session, AuditAction.TRADE_EXECUTED
        )
        assert len(logs) == 1
        assert logs[0].trade_id == "trade-001"
        assert logs[0].amount_usdc == 100.0

    @pytest.mark.asyncio
    async def test_multiple_logs(self, db_session):
        svc = AuditService()
        for i in range(5):
            await svc.log(
                db_session,
                action=AuditAction.SETTINGS_CHANGED,
                user_id=1,
                details=f"Change {i}",
            )
        await db_session.commit()

        logs = await svc.get_user_logs(db_session, user_id=1, limit=3)
        assert len(logs) == 3

    @pytest.mark.asyncio
    async def test_log_with_ip(self, db_session):
        svc = AuditService()
        await svc.log(
            db_session,
            action=AuditAction.ADMIN_VIEW,
            user_id=99,
            ip_address="192.168.1.1",
        )
        await db_session.commit()

        logs = await svc.get_user_logs(db_session, user_id=99)
        assert logs[0].ip_address == "192.168.1.1"
