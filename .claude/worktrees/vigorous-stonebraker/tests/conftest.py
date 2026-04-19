"""Shared test fixtures."""

import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.models.base import Base

# Override settings for tests
os.environ["DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["FEES_WALLET"] = "0xTestFeesWallet"
os.environ["PLATFORM_FEE_RATE"] = "0.01"
os.environ["ENCRYPTION_KEY"] = "test_encryption_key_32_bytes_ok!"


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
