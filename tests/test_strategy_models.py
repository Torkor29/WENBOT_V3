"""Tests for strategy models — Strategy, Subscription, StrategySignal, etc."""

import pytest
import pytest_asyncio
from datetime import date

from bot.models.strategy import Strategy, StrategyStatus, StrategyVisibility
from bot.models.subscription import Subscription
from bot.models.strategy_signal import StrategySignal
from bot.models.daily_performance_fee import DailyPerformanceFee, PerfFeeStatus
from bot.models.strategy_user_settings import StrategyUserSettings
from bot.models.user import User


class TestStrategyModel:
    @pytest.mark.asyncio
    async def test_create_strategy(self, db_session):
        strat = Strategy(
            id="strat_test_v1",
            name="Test Strategy",
            description="A test strategy",
            status=StrategyStatus.ACTIVE,
            visibility=StrategyVisibility.PUBLIC,
            min_trade_size=2.0,
            max_trade_size=10.0,
        )
        db_session.add(strat)
        await db_session.commit()

        result = await db_session.get(Strategy, "strat_test_v1")
        assert result is not None
        assert result.name == "Test Strategy"
        assert result.status == StrategyStatus.ACTIVE
        assert result.visibility == StrategyVisibility.PUBLIC
        assert result.win_rate == 0.0
        assert result.total_trades == 0

    @pytest.mark.asyncio
    async def test_strategy_defaults(self, db_session):
        strat = Strategy(id="strat_default", name="Default")
        db_session.add(strat)
        await db_session.commit()

        result = await db_session.get(Strategy, "strat_default")
        assert result.status == StrategyStatus.TESTING
        assert result.visibility == StrategyVisibility.PRIVATE
        assert result.min_trade_size == 2.0
        assert result.max_trade_size == 10.0
        assert result.execution_delay_ms == 100


class TestSubscriptionModel:
    @pytest.mark.asyncio
    async def test_create_subscription(self, db_session):
        # Create user first
        user = User(telegram_id=123456, uuid="test-uuid-sub")
        db_session.add(user)
        strat = Strategy(id="strat_sub_test", name="Sub Test")
        db_session.add(strat)
        await db_session.commit()

        sub = Subscription(
            user_id=user.id,
            strategy_id="strat_sub_test",
            trade_size=5.0,
        )
        db_session.add(sub)
        await db_session.commit()

        result = await db_session.get(Subscription, sub.id)
        assert result is not None
        assert result.trade_size == 5.0
        assert result.is_active is True
        assert result.user_id == user.id

    @pytest.mark.asyncio
    async def test_subscription_unique_constraint(self, db_session):
        from sqlalchemy.exc import IntegrityError

        user = User(telegram_id=999888, uuid="test-uuid-unique")
        db_session.add(user)
        strat = Strategy(id="strat_unique", name="Unique Test")
        db_session.add(strat)
        await db_session.commit()

        sub1 = Subscription(user_id=user.id, strategy_id="strat_unique", trade_size=4.0)
        db_session.add(sub1)
        await db_session.commit()

        sub2 = Subscription(user_id=user.id, strategy_id="strat_unique", trade_size=6.0)
        db_session.add(sub2)

        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestStrategySignalModel:
    @pytest.mark.asyncio
    async def test_create_signal(self, db_session):
        strat = Strategy(id="strat_sig_test", name="Signal Test")
        db_session.add(strat)
        await db_session.commit()

        signal = StrategySignal(
            strategy_id="strat_sig_test",
            action="BUY",
            side="YES",
            market_slug="btc-above-100k",
            token_id="0xabc123",
            max_price=0.75,
            confidence=0.85,
        )
        db_session.add(signal)
        await db_session.commit()

        result = await db_session.get(StrategySignal, signal.id)
        assert result.action == "BUY"
        assert result.side == "YES"
        assert result.max_price == 0.75
        assert result.subscribers_count == 0


class TestDailyPerformanceFeeModel:
    @pytest.mark.asyncio
    async def test_create_perf_fee(self, db_session):
        user = User(telegram_id=111222, uuid="test-uuid-perf")
        db_session.add(user)
        await db_session.commit()

        fee = DailyPerformanceFee(
            user_id=user.id,
            fee_date=date(2026, 3, 15),
            total_trades=10,
            wins=7,
            losses=3,
            total_pnl=25.50,
            perf_fee_rate=0.05,
            perf_fee_amount=1.275,
            status=PerfFeeStatus.SENT,
        )
        db_session.add(fee)
        await db_session.commit()

        result = await db_session.get(DailyPerformanceFee, fee.id)
        assert result.total_pnl == 25.50
        assert result.perf_fee_amount == 1.275
        assert result.status == PerfFeeStatus.SENT
        assert result.wins == 7

    @pytest.mark.asyncio
    async def test_perf_fee_skip(self, db_session):
        user = User(telegram_id=111333, uuid="test-uuid-perf2")
        db_session.add(user)
        await db_session.commit()

        fee = DailyPerformanceFee(
            user_id=user.id,
            fee_date=date(2026, 3, 16),
            total_trades=5,
            wins=1,
            losses=4,
            total_pnl=-10.0,
            status=PerfFeeStatus.SKIPPED,
        )
        db_session.add(fee)
        await db_session.commit()

        result = await db_session.get(DailyPerformanceFee, fee.id)
        assert result.status == PerfFeeStatus.SKIPPED
        assert result.total_pnl == -10.0


class TestStrategyUserSettingsModel:
    @pytest.mark.asyncio
    async def test_create_settings(self, db_session):
        user = User(telegram_id=444555, uuid="test-uuid-sus")
        db_session.add(user)
        await db_session.commit()

        sus = StrategyUserSettings(
            user_id=user.id,
            trade_fee_rate=0.03,
            max_trades_per_day=25,
        )
        db_session.add(sus)
        await db_session.commit()

        result = await db_session.get(StrategyUserSettings, sus.id)
        assert result.trade_fee_rate == 0.03
        assert result.max_trades_per_day == 25
        assert result.is_paused is False
        assert result.matic_refills_count == 0

    @pytest.mark.asyncio
    async def test_settings_defaults(self, db_session):
        user = User(telegram_id=444666, uuid="test-uuid-sus2")
        db_session.add(user)
        await db_session.commit()

        sus = StrategyUserSettings(user_id=user.id)
        db_session.add(sus)
        await db_session.commit()

        result = await db_session.get(StrategyUserSettings, sus.id)
        assert result.trade_fee_rate == 0.01
        assert result.max_trades_per_day == 50
        assert result.trades_today == 0
        assert result.matic_total_sent == 0.0


class TestTradeStrategyFields:
    @pytest.mark.asyncio
    async def test_trade_with_strategy_id(self, db_session):
        """Verify the new strategy fields on Trade model."""
        from bot.models.trade import Trade, TradeStatus, TradeSide

        user = User(telegram_id=777888, uuid="test-uuid-trade")
        db_session.add(user)
        strat = Strategy(id="strat_trade_test", name="Trade Test")
        db_session.add(strat)
        await db_session.commit()

        trade = Trade(
            trade_id="test-trade-001",
            user_id=user.id,
            market_id="market-123",
            token_id="token-abc",
            side=TradeSide.BUY,
            price=0.65,
            gross_amount_usdc=10.0,
            net_amount_usdc=9.90,
            # Strategy fields
            strategy_id="strat_trade_test",
            strategy_fee_rate=0.01,
            strategy_fee_amount=0.10,
            execution_priority=0,
        )
        db_session.add(trade)
        await db_session.commit()

        result = await db_session.get(Trade, trade.id)
        assert result.strategy_id == "strat_trade_test"
        assert result.strategy_fee_rate == 0.01
        assert result.execution_priority == 0
        assert result.result is None  # Not yet resolved
        assert result.pnl is None

    @pytest.mark.asyncio
    async def test_trade_without_strategy_id(self, db_session):
        """Copy wallet trades should have strategy_id = None."""
        from bot.models.trade import Trade, TradeStatus, TradeSide

        user = User(telegram_id=777999, uuid="test-uuid-trade2")
        db_session.add(user)
        await db_session.commit()

        trade = Trade(
            trade_id="test-trade-002",
            user_id=user.id,
            market_id="market-456",
            token_id="token-def",
            side=TradeSide.BUY,
            price=0.50,
            gross_amount_usdc=20.0,
            net_amount_usdc=19.80,
            master_wallet="0xMasterWallet",
        )
        db_session.add(trade)
        await db_session.commit()

        result = await db_session.get(Trade, trade.id)
        assert result.strategy_id is None
        assert result.master_wallet == "0xMasterWallet"


class TestUserStrategyWallet:
    @pytest.mark.asyncio
    async def test_strategy_wallet_fields(self, db_session):
        user = User(
            telegram_id=888999,
            uuid="test-uuid-wallet",
            wallet_address="0xCopyWallet",
            strategy_wallet_address="0xStratWallet",
        )
        db_session.add(user)
        await db_session.commit()

        result = await db_session.get(User, user.id)
        assert result.wallet_address == "0xCopyWallet"
        assert result.strategy_wallet_address == "0xStratWallet"
        assert result.strategy_wallet_auto_created is False


class TestGroupConfigStrategyTopics:
    @pytest.mark.asyncio
    async def test_strategy_topic_fields(self, db_session):
        from bot.models.group_config import GroupConfig

        config = GroupConfig(
            group_id=-100123456,
            topic_signals_id=1,
            topic_traders_id=2,
            topic_portfolio_id=3,
            topic_alerts_id=4,
            topic_admin_id=5,
            topic_strategies_id=6,
            topic_strategies_perf_id=7,
        )
        db_session.add(config)
        await db_session.commit()

        result = await db_session.get(GroupConfig, config.id)
        assert result.topic_strategies_id == 6
        assert result.topic_strategies_perf_id == 7
        assert result.all_topics_created is True

        topics = result.topics_dict
        assert topics["strategies"] == 6
        assert topics["strategies_perf"] == 7

    @pytest.mark.asyncio
    async def test_all_topics_requires_strategy_topics(self, db_session):
        from bot.models.group_config import GroupConfig

        config = GroupConfig(
            group_id=-100999888,
            topic_signals_id=1,
            topic_traders_id=2,
            topic_portfolio_id=3,
            topic_alerts_id=4,
            topic_admin_id=5,
            # Missing strategy topics
        )
        db_session.add(config)
        await db_session.commit()

        result = await db_session.get(GroupConfig, config.id)
        assert result.all_topics_created is False
