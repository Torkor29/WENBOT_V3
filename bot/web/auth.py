"""Telegram Mini App authentication — initData HMAC-SHA256 validation.

Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

from bot.config import settings

logger = logging.getLogger(__name__)

# initData is valid for 1 hour
MAX_AGE_SECONDS = 3600


def validate_init_data(init_data: str) -> Optional[dict]:
    """Validate Telegram WebApp initData and return the user dict.

    Returns None if validation fails.
    """
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)

        # Extract hash
        received_hash = parsed.get("hash", [None])[0]
        if not received_hash:
            logger.warning("initData missing hash")
            return None

        # Check auth_date freshness
        auth_date_str = parsed.get("auth_date", [None])[0]
        if not auth_date_str:
            logger.warning("initData missing auth_date")
            return None

        auth_date = int(auth_date_str)
        if time.time() - auth_date > MAX_AGE_SECONDS:
            logger.warning("initData expired (age=%ds)", int(time.time() - auth_date))
            return None

        # Build data-check-string: sorted key=value pairs (excluding hash)
        check_pairs = []
        for key in sorted(parsed.keys()):
            if key == "hash":
                continue
            check_pairs.append(f"{key}={parsed[key][0]}")
        data_check_string = "\n".join(check_pairs)

        # HMAC-SHA256 validation
        # secret_key = HMAC-SHA256("WebAppData", bot_token)
        secret_key = hmac.new(
            b"WebAppData",
            settings.telegram_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            logger.warning("initData HMAC mismatch")
            return None

        # Parse user JSON
        user_raw = parsed.get("user", [None])[0]
        if not user_raw:
            logger.warning("initData missing user field")
            return None

        user = json.loads(unquote(user_raw))
        return user

    except Exception as e:
        logger.error("initData validation error: %s", e)
        return None
