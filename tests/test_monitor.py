"""Tests for multi-master position monitor."""

import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"
os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"

from bot.services.monitor import MultiMasterMonitor, TradeSignal, WalletState
from bot.services.polymarket import Position


WALLET_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
WALLET_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def make_position(**overrides):
    defaults = {
        "market_id": "market-001",
        "token_id": "token-abc",
        "outcome": "YES",
        "size": 100.0,
        "avg_price": 0.5,
        "current_price": 0.55,
        "pnl_pct": 10.0,
    }
    defaults.update(overrides)
    return Position(**defaults)


class TestTradeSignal:
    def test_signal_creation(self):
        signal = TradeSignal(
            master_wallet=WALLET_A,
            market_id="m1",
            token_id="t1",
            outcome="YES",
            side="BUY",
            size=50.0,
            price=0.34,
        )
        assert signal.side == "BUY"
        assert signal.size == 50.0
        assert signal.master_wallet == WALLET_A
        assert signal.master_pnl_pct == 0.0


class TestWalletState:
    def test_initial_state(self):
        state = WalletState()
        assert state.positions == {}
        assert state.initialized is False


class TestMultiMasterMonitor:
    def test_init(self):
        monitor = MultiMasterMonitor(poll_interval=30)
        assert monitor._poll_interval == 30
        assert not monitor.is_running
        assert monitor.watched_wallets == []

    @pytest.mark.asyncio
    async def test_detect_new_position(self):
        """Monitor should emit BUY signal for new positions."""
        signals = []

        async def capture_signal(signal):
            signals.append(signal)

        monitor = MultiMasterMonitor(on_signal=capture_signal)
        monitor._wallet_states[WALLET_A] = WalletState(
            positions={}, initialized=True,
        )

        new_pos = make_position(token_id="token-new", size=100.0)

        with patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[new_pos],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 1
        assert signals[0].side == "BUY"
        assert signals[0].size == 100.0
        assert signals[0].token_id == "token-new"
        assert signals[0].master_wallet == WALLET_A

    @pytest.mark.asyncio
    async def test_detect_increased_position(self):
        """Monitor should emit BUY signal when position size increases."""
        signals = []

        async def capture_signal(signal):
            signals.append(signal)

        monitor = MultiMasterMonitor(on_signal=capture_signal)

        old_pos = make_position(token_id="token-x", size=100.0)
        monitor._wallet_states[WALLET_A] = WalletState(
            positions={"token-x": old_pos}, initialized=True,
        )

        new_pos = make_position(token_id="token-x", size=150.0)

        with patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[new_pos],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 1
        assert signals[0].side == "BUY"
        assert signals[0].size == 50.0

    @pytest.mark.asyncio
    async def test_detect_decreased_position(self):
        """Monitor should emit SELL signal when position decreases."""
        signals = []

        async def capture_signal(signal):
            signals.append(signal)

        monitor = MultiMasterMonitor(on_signal=capture_signal)

        old_pos = make_position(token_id="token-y", size=200.0)
        monitor._wallet_states[WALLET_A] = WalletState(
            positions={"token-y": old_pos}, initialized=True,
        )

        new_pos = make_position(token_id="token-y", size=80.0)

        with patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[new_pos],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 1
        assert signals[0].side == "SELL"
        assert signals[0].size == 120.0

    @pytest.mark.asyncio
    async def test_detect_closed_position(self):
        """Monitor should emit SELL signal when position disappears."""
        signals = []

        async def capture_signal(signal):
            signals.append(signal)

        monitor = MultiMasterMonitor(on_signal=capture_signal)

        old_pos = make_position(token_id="token-gone", size=50.0)
        monitor._wallet_states[WALLET_A] = WalletState(
            positions={"token-gone": old_pos}, initialized=True,
        )

        with patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 1
        assert signals[0].side == "SELL"
        assert signals[0].size == 50.0

    @pytest.mark.asyncio
    async def test_no_changes_no_signals(self):
        """No signals when positions haven't changed."""
        signals = []

        async def capture_signal(signal):
            signals.append(signal)

        monitor = MultiMasterMonitor(on_signal=capture_signal)

        pos = make_position(token_id="token-stable", size=100.0)
        monitor._wallet_states[WALLET_A] = WalletState(
            positions={"token-stable": pos}, initialized=True,
        )

        with patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[pos],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_signal_handler_error_doesnt_crash(self):
        """Monitor should continue even if signal handler throws."""
        async def bad_handler(signal):
            raise ValueError("handler error")

        monitor = MultiMasterMonitor(on_signal=bad_handler)
        monitor._wallet_states[WALLET_A] = WalletState(
            positions={}, initialized=True,
        )

        new_pos = make_position(token_id="token-err")

        with patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[new_pos],
        ):
            await monitor._check_wallet(WALLET_A)

    @pytest.mark.asyncio
    async def test_multiple_wallets_independent(self):
        """Each wallet is tracked independently."""
        signals = []

        async def capture_signal(signal):
            signals.append(signal)

        monitor = MultiMasterMonitor(on_signal=capture_signal)

        pos_a = make_position(token_id="token-a", size=50.0)
        pos_b = make_position(token_id="token-b", size=75.0)

        monitor._wallet_states[WALLET_A] = WalletState(
            positions={}, initialized=True,
        )
        monitor._wallet_states[WALLET_B] = WalletState(
            positions={}, initialized=True,
        )

        async def mock_positions(wallet):
            if wallet == WALLET_A:
                return [pos_a]
            elif wallet == WALLET_B:
                return [pos_b]
            return []

        with patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            side_effect=mock_positions,
        ):
            await monitor._check_all_wallets()

        assert len(signals) == 2
        wallet_signals = {s.master_wallet: s for s in signals}
        assert wallet_signals[WALLET_A].token_id == "token-a"
        assert wallet_signals[WALLET_B].token_id == "token-b"

    def test_watched_wallets_property(self):
        monitor = MultiMasterMonitor()
        monitor._wallet_states[WALLET_A] = WalletState()
        monitor._wallet_states[WALLET_B] = WalletState()
        assert set(monitor.watched_wallets) == {WALLET_A, WALLET_B}
