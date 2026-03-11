"""Tests for user service — CRUD operations."""

import os
import pytest
import pytest_asyncio
from sqlalchemy import select

os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"
os.environ["FEES_WALLET"] = "0xTestFeesWallet"

from bot.models.user import User, UserRole
from bot.models.settings import UserSettings, SizingMode
from bot.services.user_service import (
    get_user_by_telegram_id,
    create_user,
    save_wallet,
    get_or_create_settings,
    update_setting,
    get_all_active_followers,
    get_followers_of_wallet,
    get_all_followed_wallets,
    get_admin_stats,
)
from bot.services.crypto import decrypt_private_key
from bot.config import settings


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_create_follower(self, db_session):
        user = await create_user(db_session, telegram_id=100001, username="testuser")
        assert user.telegram_id == 100001
        assert user.telegram_username == "testuser"
        assert user.role == UserRole.FOLLOWER
        assert user.uuid is not None
        assert user.is_active is True
        assert user.paper_trading is True

    @pytest.mark.asyncio
    async def test_create_admin(self, db_session):
        user = await create_user(db_session, telegram_id=100002, role=UserRole.ADMIN)
        assert user.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_creates_default_settings(self, db_session):
        user = await create_user(db_session, telegram_id=100003)
        result = await db_session.execute(
            select(UserSettings).where(UserSettings.user_id == user.id)
        )
        us = result.scalar_one()
        assert us.allocated_capital == 100.0
        assert us.sizing_mode == SizingMode.FIXED


class TestGetUser:
    @pytest.mark.asyncio
    async def test_get_existing_user(self, db_session):
        await create_user(db_session, telegram_id=200001)
        user = await get_user_by_telegram_id(db_session, 200001)
        assert user is not None
        assert user.telegram_id == 200001

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, db_session):
        user = await get_user_by_telegram_id(db_session, 999999)
        assert user is None


class TestSaveWallet:
    @pytest.mark.asyncio
    async def test_save_polygon_wallet(self, db_session):
        user = await create_user(db_session, telegram_id=300001)
        await save_wallet(
            db_session, user,
            wallet_address="0x1234567890abcdef1234567890abcdef12345678",
            private_key="0xdeadbeef_private_key_here",
            chain="polygon",
        )
        assert user.wallet_address == "0x1234567890abcdef1234567890abcdef12345678"
        assert user.encrypted_private_key is not None
        # Verify it decrypts correctly
        decrypted = decrypt_private_key(
            user.encrypted_private_key,
            settings.encryption_key,
            user.uuid,
        )
        assert decrypted == "0xdeadbeef_private_key_here"

    @pytest.mark.asyncio
    async def test_save_solana_wallet(self, db_session):
        user = await create_user(db_session, telegram_id=300002)
        await save_wallet(
            db_session, user,
            wallet_address="SoLaNaWaLlEtAdDrEsS123",
            private_key="solana_secret_key_bytes",
            chain="solana",
        )
        assert user.solana_wallet_address == "SoLaNaWaLlEtAdDrEsS123"
        assert user.encrypted_solana_key is not None


class TestSettings:
    @pytest.mark.asyncio
    async def test_get_or_create_settings(self, db_session):
        user = await create_user(db_session, telegram_id=400001)
        us = await get_or_create_settings(db_session, user)
        assert us is not None
        assert us.user_id == user.id

    @pytest.mark.asyncio
    async def test_update_setting(self, db_session):
        user = await create_user(db_session, telegram_id=400002)
        us = await get_or_create_settings(db_session, user)
        await update_setting(db_session, us, "allocated_capital", 500.0)
        assert us.allocated_capital == 500.0

    @pytest.mark.asyncio
    async def test_update_sizing_mode(self, db_session):
        user = await create_user(db_session, telegram_id=400003)
        us = await get_or_create_settings(db_session, user)
        await update_setting(db_session, us, "sizing_mode", SizingMode.PROPORTIONAL)
        assert us.sizing_mode == SizingMode.PROPORTIONAL


class TestActiveFollowers:
    @pytest.mark.asyncio
    async def test_get_active_followers(self, db_session):
        await create_user(db_session, telegram_id=500001)
        await create_user(db_session, telegram_id=500002)
        u3 = await create_user(db_session, telegram_id=500003)
        u3.is_paused = True
        await db_session.commit()

        followers = await get_all_active_followers(db_session)
        active_ids = {f.telegram_id for f in followers}
        assert 500001 in active_ids
        assert 500002 in active_ids
        assert 500003 not in active_ids  # paused

    @pytest.mark.asyncio
    async def test_admins_excluded(self, db_session):
        await create_user(db_session, telegram_id=600001, role=UserRole.ADMIN)
        await create_user(db_session, telegram_id=600002)
        followers = await get_all_active_followers(db_session)
        ids = {f.telegram_id for f in followers}
        assert 600001 not in ids
        assert 600002 in ids


class TestFollowedWallets:
    @pytest.mark.asyncio
    async def test_get_all_followed_wallets(self, db_session):
        u1 = await create_user(db_session, telegram_id=700001)
        u2 = await create_user(db_session, telegram_id=700002)
        us1 = await get_or_create_settings(db_session, u1)
        us2 = await get_or_create_settings(db_session, u2)

        wallet_a = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        wallet_b = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

        await update_setting(db_session, us1, "followed_wallets", [wallet_a, wallet_b])
        await update_setting(db_session, us2, "followed_wallets", [wallet_a])

        wallets = await get_all_followed_wallets(db_session)
        assert wallet_a in wallets
        assert wallet_b in wallets
        assert len(wallets) == 2

    @pytest.mark.asyncio
    async def test_get_followers_of_wallet(self, db_session):
        u1 = await create_user(db_session, telegram_id=800001)
        u2 = await create_user(db_session, telegram_id=800002)
        u3 = await create_user(db_session, telegram_id=800003)
        us1 = await get_or_create_settings(db_session, u1)
        us2 = await get_or_create_settings(db_session, u2)
        us3 = await get_or_create_settings(db_session, u3)

        wallet_a = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        wallet_b = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

        await update_setting(db_session, us1, "followed_wallets", [wallet_a])
        await update_setting(db_session, us2, "followed_wallets", [wallet_a, wallet_b])
        await update_setting(db_session, us3, "followed_wallets", [wallet_b])

        followers_a = await get_followers_of_wallet(db_session, wallet_a)
        followers_b = await get_followers_of_wallet(db_session, wallet_b)

        assert len(followers_a) == 2
        assert len(followers_b) == 2
        ids_a = {f.telegram_id for f in followers_a}
        assert 800001 in ids_a
        assert 800002 in ids_a

    @pytest.mark.asyncio
    async def test_no_followed_wallets(self, db_session):
        await create_user(db_session, telegram_id=900001)
        wallets = await get_all_followed_wallets(db_session)
        assert len(wallets) == 0


class TestAdminStats:
    @pytest.mark.asyncio
    async def test_empty_stats(self, db_session):
        stats = await get_admin_stats(db_session)
        assert stats["follower_count"] == 0
        assert stats["trade_count"] == 0
        assert stats["total_volume"] == 0.0
        assert stats["total_fees"] == 0.0
