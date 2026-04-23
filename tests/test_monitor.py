"""Tests for multi-master activity monitor (activity-driven detection)."""

import os
import pytest
from unittest.mock import AsyncMock, patch

os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"
os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"

from bot.services.monitor import MultiMasterMonitor, TradeSignal, WalletState
from bot.services.polymarket import Position, Activity


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


def make_activity(**overrides):
    defaults = {
        "timestamp": 1_700_000_000,
        "market_id": "market-001",
        "title": "Will X happen?",
        "outcome": "YES",
        "side": "BUY",
        "size": 100.0,
        "usdc_size": 50.0,
        "price": 0.5,
        "tx_hash": "0x" + "ab" * 32,
        "slug": "will-x-happen",
        "token_id": "token-abc",
    }
    defaults.update(overrides)
    return Activity(**defaults)


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
        assert state.last_activity_ts == 0
        assert list(state.seen_tx_hashes) == []

    def test_mark_seen_dedups(self):
        state = WalletState()
        state.mark_seen("0xabc")
        state.mark_seen("0xabc")  # no-op
        assert state.has_seen("0xabc")
        assert len(state.seen_tx_hashes) == 1

    def test_mark_seen_evicts_oldest_when_full(self):
        state = WalletState()
        # Force small maxlen to exercise eviction
        from collections import deque
        state.seen_tx_hashes = deque(maxlen=3)
        for h in ("a", "b", "c", "d"):
            state.mark_seen(h)
        assert not state.has_seen("a")  # evicted
        assert state.has_seen("d")
        assert len(state.seen_tx_hashes) == 3


class TestMultiMasterMonitorActivity:
    def test_init(self):
        monitor = MultiMasterMonitor(poll_interval=30)
        assert monitor._poll_interval == 30
        assert not monitor.is_running
        assert monitor.watched_wallets == []

    @pytest.mark.asyncio
    async def test_idle_wallet_no_activity_no_signal(self):
        """Si /activity renvoie rien : pas de signal, pas d'appel positions."""
        signals = []
        monitor = MultiMasterMonitor(on_signal=lambda s: signals.append(s) or AsyncMock()())

        async def capture(s): signals.append(s)
        monitor._on_signal = capture
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_act, patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_pos:
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 0
        mock_act.assert_awaited_once()
        mock_pos.assert_not_awaited()  # skipped when no activity → 1 HTTP call idle

    @pytest.mark.asyncio
    async def test_buy_activity_emits_buy_signal(self):
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        act = make_activity(
            side="BUY", size=42.0, price=0.61, token_id="token-new",
            market_id="market-42", tx_hash="0xdeadbeef", timestamp=1700000100,
        )

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[act],
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[make_position(token_id="token-new", size=42.0)],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 1
        s = signals[0]
        assert s.side == "BUY"
        assert s.size == 42.0
        assert s.token_id == "token-new"
        assert s.market_id == "market-42"
        state = monitor._wallet_states[WALLET_A]
        assert state.last_activity_ts == 1700000100
        assert state.has_seen("0xdeadbeef")

    @pytest.mark.asyncio
    async def test_sell_activity_computes_sell_ratio_from_remaining(self):
        """SELL signal : sell_ratio = size_vendue / (restant + size_vendue)."""
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        # Master sold 30 sh, currently has 70 sh left → sold 30/100 = 30 %.
        sell_act = make_activity(
            side="SELL", size=30.0, price=0.62, token_id="token-x",
            tx_hash="0xsell1",
        )
        remaining_pos = make_position(token_id="token-x", size=70.0)

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[sell_act],
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[remaining_pos],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 1
        s = signals[0]
        assert s.side == "SELL"
        assert s.size == 30.0
        assert abs(s.sell_ratio - 0.30) < 1e-6

    @pytest.mark.asyncio
    async def test_full_close_sell_ratio_is_1(self):
        """SELL qui ferme toute la position → sell_ratio = 1.0."""
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        sell_act = make_activity(
            side="SELL", size=50.0, token_id="token-closed",
            tx_hash="0xfull",
        )
        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[sell_act],
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[],  # position entièrement liquidée
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 1
        assert signals[0].sell_ratio == 1.0

    @pytest.mark.asyncio
    async def test_dedup_same_tx_across_polls(self):
        """La même activity ne doit PAS être re-émise sur un 2ᵉ poll."""
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        act = make_activity(tx_hash="0xrepeat", timestamp=1700001000)

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[act],
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[make_position()],
        ):
            await monitor._check_wallet(WALLET_A)  # 1st poll
            await monitor._check_wallet(WALLET_A)  # 2nd poll, same activity

        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_multiple_activities_emitted_in_order(self):
        """Activities triées chrono ASC : émet dans l'ordre temporel."""
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        acts = [
            make_activity(tx_hash="0xone", timestamp=1700000001, size=10.0),
            make_activity(tx_hash="0xtwo", timestamp=1700000003, size=20.0),
            make_activity(tx_hash="0xthree", timestamp=1700000002, size=30.0),
        ]
        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=acts,
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[make_position()],
        ):
            await monitor._check_wallet(WALLET_A)

        assert [s.size for s in signals] == [10.0, 30.0, 20.0]
        state = monitor._wallet_states[WALLET_A]
        assert state.last_activity_ts == 1700000003

    @pytest.mark.asyncio
    async def test_dust_activity_skipped(self):
        """Une activity sous MIN_SIGNAL_SIZE (0.01 sh) est ignorée mais marquée vue."""
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        dust = make_activity(size=0.001, tx_hash="0xdust")

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[dust],
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[make_position()],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 0
        assert monitor._wallet_states[WALLET_A].has_seen("0xdust")

    @pytest.mark.asyncio
    async def test_sell_on_resolved_market_skipped(self):
        """SELL sur marché résolu = REDEEM, pas un SELL copiable."""
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        act = make_activity(side="SELL", size=50.0, tx_hash="0xredeem", token_id="tok-R")
        resolved_pos = make_position(token_id="tok-R", size=0.0)
        resolved_pos.redeemable = True

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[act],
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[resolved_pos],
        ):
            await monitor._check_wallet(WALLET_A)

        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_uninitialized_wallet_returns_early(self):
        """Sans snapshot initial, _check_wallet ne fait rien."""
        monitor = MultiMasterMonitor()
        monitor._wallet_states[WALLET_A] = WalletState(initialized=False)

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[make_activity()],
        ) as m:
            await monitor._check_wallet(WALLET_A)

        m.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_signal_handler_error_doesnt_crash(self):
        async def bad_handler(signal):
            raise ValueError("handler error")

        monitor = MultiMasterMonitor(on_signal=bad_handler)
        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            new_callable=AsyncMock,
            return_value=[make_activity(tx_hash="0xkaboom")],
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            new_callable=AsyncMock,
            return_value=[make_position()],
        ):
            # ne doit pas lever
            await monitor._check_wallet(WALLET_A)

    @pytest.mark.asyncio
    async def test_multiple_wallets_independent(self):
        signals = []
        async def capture(s): signals.append(s)
        monitor = MultiMasterMonitor(on_signal=capture)

        monitor._wallet_states[WALLET_A] = WalletState(initialized=True)
        monitor._wallet_states[WALLET_B] = WalletState(initialized=True)

        act_a = make_activity(tx_hash="0xA", token_id="tA")
        act_b = make_activity(tx_hash="0xB", token_id="tB")

        async def mock_activity(wallet, **kw):
            return [act_a] if wallet == WALLET_A else [act_b]

        async def mock_positions(wallet):
            tok = "tA" if wallet == WALLET_A else "tB"
            return [make_position(token_id=tok)]

        with patch(
            "bot.services.monitor.polymarket_client.get_activity_by_address",
            side_effect=mock_activity,
        ), patch(
            "bot.services.monitor.polymarket_client.get_positions_by_address",
            side_effect=mock_positions,
        ):
            await monitor._check_all_wallets()

        assert len(signals) == 2
        by_wallet = {s.master_wallet: s for s in signals}
        assert by_wallet[WALLET_A].token_id == "tA"
        assert by_wallet[WALLET_B].token_id == "tB"

    def test_watched_wallets_property(self):
        monitor = MultiMasterMonitor()
        monitor._wallet_states[WALLET_A] = WalletState()
        monitor._wallet_states[WALLET_B] = WalletState()
        assert set(monitor.watched_wallets) == {WALLET_A, WALLET_B}
