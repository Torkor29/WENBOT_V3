"""Tests for Polymarket order placement — slippage tolerance + FOK→FAK fallback."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"
os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"

from bot.services.polymarket import PolymarketClient, OrderResult


FAKE_PK = "0x" + "1" * 64
TOKEN = "0xtoken123"


def _fake_clob_result(success=True, order_id="ord-1", taking=0, making=0, err=None):
    d = {}
    if success:
        d["success"] = True
        d["orderID"] = order_id
    else:
        d["success"] = False
        if err:
            d["errorMsg"] = err
    if taking:
        d["takingAmount"] = str(taking)
    if making:
        d["makingAmount"] = str(making)
    return d


class _FakeOrderType:
    FOK = "FOK"
    FAK = "FAK"
    GTC = "GTC"


class _FakeMarketOrderArgs:
    def __init__(self, **kw):
        self.kw = kw


def _patch_clob_types():
    """Patch py_clob_client.clob_types so tests don't need the real lib."""
    fake = MagicMock()
    fake.OrderType = _FakeOrderType
    fake.MarketOrderArgs = _FakeMarketOrderArgs
    fake.OrderArgs = _FakeMarketOrderArgs
    return patch.dict("sys.modules", {"py_clob_client.clob_types": fake})


class TestSlippagePrice:
    @pytest.mark.asyncio
    async def test_buy_limit_price_includes_slippage(self):
        """BUY : limit_price = signal_price × (1 + slippage)."""
        client = PolymarketClient()
        captured = {}

        def fake_create(order):
            captured["price"] = order.kw.get("price")
            captured["side"] = order.kw.get("side")
            return "signed"

        def fake_post(signed, order_type):
            return _fake_clob_result(taking=100, making=50)

        user = MagicMock()
        user.create_market_order = fake_create
        user.post_order = fake_post
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            res = await client.place_market_order(
                FAKE_PK, TOKEN, "BUY", amount_usdc=50.0,
                signal_price=0.50, max_slippage_bps=300,
            )

        assert res.success
        # 0.50 × 1.03 = 0.515
        assert abs(captured["price"] - 0.515) < 1e-9
        assert captured["side"] == "BUY"

    @pytest.mark.asyncio
    async def test_sell_limit_price_subtracts_slippage(self):
        """SELL : limit_price = signal_price × (1 - slippage)."""
        client = PolymarketClient()
        captured = {}

        def fake_create(order):
            captured["price"] = order.kw.get("price")
            return "signed"

        def fake_post(signed, order_type):
            return _fake_clob_result(taking=20, making=50)

        user = MagicMock()
        user.create_market_order = fake_create
        user.post_order = fake_post
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            res = await client.place_market_order(
                FAKE_PK, TOKEN, "SELL", amount_usdc=50.0,
                signal_price=0.40, max_slippage_bps=500,
            )

        assert res.success
        # 0.40 × 0.95 = 0.38
        assert abs(captured["price"] - 0.38) < 1e-9

    @pytest.mark.asyncio
    async def test_buy_limit_capped_at_99cents(self):
        """Un signal à 0.98 + 5% de slippage ne doit pas dépasser 0.99."""
        client = PolymarketClient()
        captured = {}

        def fake_create(order):
            captured["price"] = order.kw.get("price")
            return "signed"

        user = MagicMock()
        user.create_market_order = fake_create
        user.post_order = lambda s, t: _fake_clob_result(taking=1, making=1)
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            await client.place_market_order(
                FAKE_PK, TOKEN, "BUY", 10.0,
                signal_price=0.98, max_slippage_bps=500,
            )
        assert captured["price"] == pytest.approx(0.99)

    @pytest.mark.asyncio
    async def test_sell_limit_floored_at_1cent(self):
        client = PolymarketClient()
        captured = {}
        def fake_create(order):
            captured["price"] = order.kw.get("price")
            return "signed"
        user = MagicMock()
        user.create_market_order = fake_create
        user.post_order = lambda s, t: _fake_clob_result(taking=1, making=1)
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            await client.place_market_order(
                FAKE_PK, TOKEN, "SELL", 10.0,
                signal_price=0.02, max_slippage_bps=5000,  # 50 %
            )
        assert captured["price"] == pytest.approx(0.01)


class TestFOKFAKFallback:
    @pytest.mark.asyncio
    async def test_fok_success_no_fallback(self):
        """FOK réussit → pas de tentative FAK."""
        client = PolymarketClient()
        calls = []

        def fake_post(signed, order_type):
            calls.append(order_type)
            return _fake_clob_result(taking=100, making=50, order_id="FOK-1")

        user = MagicMock()
        user.create_market_order = lambda o: "signed"
        user.post_order = fake_post
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            res = await client.place_market_order(
                FAKE_PK, TOKEN, "BUY", 50.0,
                signal_price=0.50, max_slippage_bps=300,
            )

        assert res.success
        assert res.filled_size == 100.0
        assert calls == [_FakeOrderType.FOK]

    @pytest.mark.asyncio
    async def test_fok_rejected_fallbacks_to_fak(self):
        """FOK rejeté → FAK tenté. FAK réussit avec partial fill."""
        client = PolymarketClient()
        calls = []

        def fake_post(signed, order_type):
            calls.append(order_type)
            if order_type == _FakeOrderType.FOK:
                return _fake_clob_result(success=False, err="no liquidity")
            return _fake_clob_result(taking=60, making=30, order_id="FAK-1")

        user = MagicMock()
        user.create_market_order = lambda o: "signed"
        user.post_order = fake_post
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            res = await client.place_market_order(
                FAKE_PK, TOKEN, "BUY", 50.0,
                signal_price=0.50, max_slippage_bps=300,
            )

        assert res.success
        assert res.filled_size == 60.0  # partial fill BUY : shares = takingAmount
        assert res.avg_price == pytest.approx(30.0 / 60.0)
        assert calls == [_FakeOrderType.FOK, _FakeOrderType.FAK]

    @pytest.mark.asyncio
    async def test_both_rejected_returns_failure(self):
        client = PolymarketClient()

        def fake_post(signed, order_type):
            return _fake_clob_result(success=False, err="rejected")

        user = MagicMock()
        user.create_market_order = lambda o: "signed"
        user.post_order = fake_post
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            res = await client.place_market_order(
                FAKE_PK, TOKEN, "BUY", 50.0,
                signal_price=0.50, max_slippage_bps=300,
            )

        assert res.success is False
        assert "reject" in (res.error or "").lower()

    @pytest.mark.asyncio
    async def test_sell_shares_mapped_from_making_amount(self):
        """Pour un SELL, takingAmount = USDC reçus, makingAmount = shares vendues.
        Le OrderResult doit refléter filled_size en shares, avg_price en USDC/share."""
        client = PolymarketClient()

        def fake_post(signed, order_type):
            # SELL : taking=80 USDC reçus, making=200 shares vendues
            return _fake_clob_result(taking=80, making=200, order_id="SELL-1")

        user = MagicMock()
        user.create_market_order = lambda o: "signed"
        user.post_order = fake_post
        client.create_user_client = lambda pk: user

        with _patch_clob_types():
            res = await client.place_market_order(
                FAKE_PK, TOKEN, "SELL", 80.0,
                signal_price=0.40, max_slippage_bps=300,
            )

        assert res.success
        assert res.filled_size == 200.0  # shares vendues
        assert res.avg_price == pytest.approx(80.0 / 200.0)  # 0.40 USDC/share
