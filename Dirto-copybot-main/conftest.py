"""Root conftest — set test environment variables before any module import."""

import os

os.environ.setdefault("ENCRYPTION_MASTER_KEY", "a" * 64)
os.environ.setdefault("WENBOT_FEE_WALLET", "0x" + "f" * 40)
os.environ.setdefault("WENBOT_PRIVATE_KEY", "0x" + "1" * 64)
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("TELEGRAM_TOKEN", "000000000:test-token")
