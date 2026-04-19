"""2FA OTP service for critical actions.

Generates time-limited OTP codes sent via Telegram.
Used for: large trades (above threshold), stop/disable commands, key changes.
"""

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# OTP settings
OTP_LENGTH = 6
OTP_EXPIRY_SECONDS = 300  # 5 minutes
OTP_MAX_ATTEMPTS = 3


@dataclass
class OTPChallenge:
    code: str
    user_id: int
    action: str
    created_at: float
    expires_at: float
    attempts: int = 0
    verified: bool = False


class OTPService:
    """In-memory OTP service for 2FA confirmation."""

    def __init__(self):
        self._pending: dict[str, OTPChallenge] = {}  # key = f"{user_id}:{action}"

    def generate(self, user_id: int, action: str) -> OTPChallenge:
        """Generate a new OTP for a user action.

        Args:
            user_id: Telegram user ID.
            action: Action description (e.g., "trade_confirm", "stop_bot").

        Returns:
            OTPChallenge with the code to send to the user.
        """
        code = "".join([str(secrets.randbelow(10)) for _ in range(OTP_LENGTH)])
        now = time.time()

        challenge = OTPChallenge(
            code=code,
            user_id=user_id,
            action=action,
            created_at=now,
            expires_at=now + OTP_EXPIRY_SECONDS,
        )

        key = f"{user_id}:{action}"
        self._pending[key] = challenge

        logger.info(f"OTP generated for user {user_id}, action: {action}")
        return challenge

    def verify(self, user_id: int, action: str, code: str) -> tuple[bool, str]:
        """Verify an OTP code.

        Returns:
            (success, message) tuple.
        """
        key = f"{user_id}:{action}"
        challenge = self._pending.get(key)

        if not challenge:
            return False, "Aucun code OTP en attente pour cette action."

        if challenge.verified:
            return False, "Ce code a déjà été utilisé."

        if time.time() > challenge.expires_at:
            del self._pending[key]
            return False, "Code OTP expiré. Demandez un nouveau code."

        challenge.attempts += 1
        if challenge.attempts > OTP_MAX_ATTEMPTS:
            del self._pending[key]
            return False, "Trop de tentatives. Demandez un nouveau code."

        if not hmac.compare_digest(challenge.code, code):
            remaining = OTP_MAX_ATTEMPTS - challenge.attempts
            return False, f"Code incorrect. {remaining} tentative(s) restante(s)."

        # Success
        challenge.verified = True
        del self._pending[key]
        logger.info(f"OTP verified for user {user_id}, action: {action}")
        return True, "Code vérifié avec succès."

    def cancel(self, user_id: int, action: str) -> None:
        """Cancel a pending OTP challenge."""
        key = f"{user_id}:{action}"
        self._pending.pop(key, None)

    def cleanup_expired(self) -> int:
        """Remove all expired OTP challenges. Returns count removed."""
        now = time.time()
        expired = [
            k for k, v in self._pending.items() if now > v.expires_at
        ]
        for k in expired:
            del self._pending[k]
        return len(expired)

    @property
    def pending_count(self) -> int:
        return len(self._pending)


# Singleton
otp_service = OTPService()
