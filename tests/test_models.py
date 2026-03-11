"""Tests for SQLAlchemy models — verify schema and relationships."""

import pytest
import pytest_asyncio
from sqlalchemy import select

from bot.models.user import User, UserRole
from bot.models.settings import UserSettings, SizingMode
from bot.models.trade import Trade, TradeStatus, TradeSide
from bot.models.fee import FeeRecord


class TestUserModel:
    @pytest.mark.asyncio
    async def test_create_user(self, db_session):
        user = User(telegram_id=12345, role=UserRole.FOLLOWER)
        db_session.add(user)
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.telegram_id == 12345))
        fetched = result.scalar_one()
        assert fetched.telegram_id == 12345
        assert fetched.role == UserRole.FOLLOWER
        assert fetched.uuid is not None
        assert fetched.is_active is True
        assert fetched.paper_trading is True

    @pytest.mark.asyncio
    async def test_create_admin(self, db_session):
        user = User(telegram_id=99999, role=UserRole.ADMIN)
        db_session.add(user)
        await db_session.commit()

        result = await db_session.execute(select(User).where(User.telegram_id == 99999))
        fetched = result.scalar_one()
        assert fetched.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_unique_telegram_id(self, db_session):
        u1 = User(telegram_id=11111)
        u2 = User(telegram_id=11111)
        db_session.add(u1)
        await db_session.commit()
        db_session.add(u2)
        with pytest.raises(Exception):
            await db_session.commit()


class TestUserSettingsModel:
    @pytest.mark.asyncio
    async def test_create_settings_with_user(self, db_session):
        user = User(telegram_id=22222)
        db_session.add(user)
        await db_session.commit()

        settings = UserSettings(
            user_id=user.id,
            allocated_capital=500.0,
            sizing_mode=SizingMode.PERCENT,
            percent_per_trade=10.0,
        )
        db_session.add(settings)
        await db_session.commit()

        result = await db_session.execute(
            select(UserSettings).where(UserSettings.user_id == user.id)
        )
        fetched = result.scalar_one()
        assert fetched.allocated_capital == 500.0
        assert fetched.sizing_mode == SizingMode.PERCENT
        assert fetched.multiplier == 1.0  # default

    @pytest.mark.asyncio
    async def test_default_values(self, db_session):
        user = User(telegram_id=33333)
        db_session.add(user)
        await db_session.commit()

        settings = UserSettings(user_id=user.id)
        db_session.add(settings)
        await db_session.commit()

        assert settings.stop_loss_pct == 20.0
        assert settings.max_trade_usdc == 100.0
        assert settings.min_trade_usdc == 1.0
        assert settings.copy_delay_seconds == 0
        assert settings.auto_bridge_sol is False


class TestTradeModel:
    @pytest.mark.asyncio
    async def test_create_trade(self, db_session):
        user = User(telegram_id=44444)
        db_session.add(user)
        await db_session.commit()

        trade = Trade(
            trade_id="trade-001",
            user_id=user.id,
            market_id="market-abc",
            token_id="token-xyz",
            side=TradeSide.BUY,
            price=0.34,
            gross_amount_usdc=45.0,
            fee_amount_usdc=0.45,
            net_amount_usdc=44.55,
            status=TradeStatus.FILLED,
        )
        db_session.add(trade)
        await db_session.commit()

        result = await db_session.execute(
            select(Trade).where(Trade.trade_id == "trade-001")
        )
        fetched = result.scalar_one()
        assert fetched.side == TradeSide.BUY
        assert fetched.net_amount_usdc == 44.55
        assert fetched.is_paper is False


class TestFeeRecordModel:
    @pytest.mark.asyncio
    async def test_create_fee_record(self, db_session):
        user = User(telegram_id=55555)
        db_session.add(user)
        await db_session.commit()

        trade = Trade(
            trade_id="trade-fee-001",
            user_id=user.id,
            market_id="m1",
            token_id="t1",
            side=TradeSide.BUY,
            price=0.5,
            gross_amount_usdc=100.0,
            net_amount_usdc=99.0,
        )
        db_session.add(trade)
        await db_session.commit()

        fee = FeeRecord(
            user_id=user.id,
            trade_id=trade.id,
            gross_amount=100.0,
            fee_rate=0.01,
            fee_amount=1.0,
            net_amount=99.0,
            fees_wallet="0xFeeWallet",
            confirmed_on_chain=True,
            tx_hash="0xabc123",
        )
        db_session.add(fee)
        await db_session.commit()

        result = await db_session.execute(
            select(FeeRecord).where(FeeRecord.trade_id == trade.id)
        )
        fetched = result.scalar_one()
        assert fetched.fee_amount == 1.0
        assert fetched.confirmed_on_chain is True
        assert fetched.tx_hash == "0xabc123"

    @pytest.mark.asyncio
    async def test_paper_trade_fee(self, db_session):
        user = User(telegram_id=66666)
        db_session.add(user)
        await db_session.commit()

        trade = Trade(
            trade_id="trade-paper-001",
            user_id=user.id,
            market_id="m2",
            token_id="t2",
            side=TradeSide.BUY,
            price=0.3,
            gross_amount_usdc=50.0,
            net_amount_usdc=49.5,
            is_paper=True,
        )
        db_session.add(trade)
        await db_session.commit()

        fee = FeeRecord(
            user_id=user.id,
            trade_id=trade.id,
            gross_amount=50.0,
            fee_rate=0.01,
            fee_amount=0.5,
            net_amount=49.5,
            fees_wallet="0xFeeWallet",
            is_paper=True,
            confirmed_on_chain=False,
        )
        db_session.add(fee)
        await db_session.commit()

        assert fee.is_paper is True
        assert fee.confirmed_on_chain is False
