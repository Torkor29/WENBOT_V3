"""Centralized configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


# ---------------------------------------------------------------------------
# Blockchain constants
# ---------------------------------------------------------------------------
USDC_CONTRACT: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_DECIMALS: int = 6

POLYMARKET_CLOB_HOST: str = os.getenv(
    "POLYMARKET_CLOB_HOST", "https://clob.polymarket.com"
)
POLYMARKET_CHAIN_ID: int = int(os.getenv("POLYMARKET_CHAIN_ID", "137"))

# ---------------------------------------------------------------------------
# WenBot operational wallet
# ---------------------------------------------------------------------------
WENBOT_FEE_WALLET: str = os.getenv("WENBOT_FEE_WALLET", "")
WENBOT_PRIVATE_KEY: str = os.getenv("WENBOT_PRIVATE_KEY", "")

# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------
ENCRYPTION_MASTER_KEY: str = os.getenv("ENCRYPTION_MASTER_KEY", "")

# ---------------------------------------------------------------------------
# External services
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

# ---------------------------------------------------------------------------
# RPC endpoints
# ---------------------------------------------------------------------------
POLYGON_RPC_URL: str = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
ALCHEMY_RPC_URL: str = os.getenv("ALCHEMY_RPC_URL", "")

# ---------------------------------------------------------------------------
# Fee structure
# ---------------------------------------------------------------------------
MIN_TRADE_FEE_RATE: float = 0.01
PERF_FEE_RATE: float = 0.05

# ---------------------------------------------------------------------------
# MATIC / POL refill settings
# ---------------------------------------------------------------------------
MATIC_REFILL_AMOUNT: float = 0.1
MATIC_MIN_BALANCE: float = 0.01
MATIC_MAX_REFILLS: int = 3
MATIC_MAX_TOTAL: float = 0.3
MATIC_REFILL_COOLDOWN_SECONDS: int = 86_400
MIN_USDC_FOR_MATIC_REFILL: float = 2.0

# ---------------------------------------------------------------------------
# Builder API (for Polymarket redeem)
# ---------------------------------------------------------------------------
BUILDER_API_KEY: str = os.getenv("BUILDER_API_KEY", "")
BUILDER_API_SECRET: str = os.getenv("BUILDER_API_SECRET", "")
BUILDER_API_PASSPHRASE: str = os.getenv("BUILDER_API_PASSPHRASE", "")
