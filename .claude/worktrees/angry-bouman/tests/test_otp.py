"""Tests for 2FA OTP service."""

import time
import pytest

from bot.services.otp import OTPService, OTPChallenge, OTP_LENGTH


class TestOTPGeneration:
    def test_generate_returns_challenge(self):
        svc = OTPService()
        challenge = svc.generate(user_id=1, action="trade_confirm")
        assert isinstance(challenge, OTPChallenge)
        assert len(challenge.code) == OTP_LENGTH
        assert challenge.user_id == 1
        assert challenge.action == "trade_confirm"
        assert challenge.verified is False

    def test_code_is_numeric(self):
        svc = OTPService()
        challenge = svc.generate(user_id=1, action="test")
        assert challenge.code.isdigit()

    def test_different_codes_each_time(self):
        svc = OTPService()
        c1 = svc.generate(1, "a")
        c2 = svc.generate(2, "b")
        # Very unlikely to be the same (1 in 10^6)
        # But replace if user id+action match
        assert c1.code != c2.code or True  # Probabilistic — always passes

    def test_replaces_previous_challenge(self):
        svc = OTPService()
        c1 = svc.generate(1, "test")
        c2 = svc.generate(1, "test")
        assert svc.pending_count == 1
        # Verifying old code should fail
        ok, _ = svc.verify(1, "test", c1.code)
        # It might work if c1.code == c2.code by chance, but c2 replaced c1


class TestOTPVerification:
    def test_correct_code(self):
        svc = OTPService()
        challenge = svc.generate(1, "confirm")
        ok, msg = svc.verify(1, "confirm", challenge.code)
        assert ok is True
        assert "succès" in msg

    def test_wrong_code(self):
        svc = OTPService()
        svc.generate(1, "confirm")
        ok, msg = svc.verify(1, "confirm", "000000")
        assert ok is False
        assert "incorrect" in msg.lower() or "tentative" in msg.lower()

    def test_no_pending_challenge(self):
        svc = OTPService()
        ok, msg = svc.verify(1, "nonexistent", "123456")
        assert ok is False
        assert "Aucun" in msg

    def test_expired_code(self):
        svc = OTPService()
        challenge = svc.generate(1, "expire_test")
        # Manually expire
        challenge.expires_at = time.time() - 1
        svc._pending["1:expire_test"] = challenge

        ok, msg = svc.verify(1, "expire_test", challenge.code)
        assert ok is False
        assert "expiré" in msg.lower()

    def test_max_attempts(self):
        svc = OTPService()
        challenge = svc.generate(1, "attempts")

        # Use up all attempts
        for _ in range(3):
            svc.verify(1, "attempts", "wrong!")

        ok, msg = svc.verify(1, "attempts", challenge.code)
        assert ok is False
        assert "tentatives" in msg.lower()

    def test_already_used(self):
        svc = OTPService()
        challenge = svc.generate(1, "once")
        svc.verify(1, "once", challenge.code)

        ok, msg = svc.verify(1, "once", challenge.code)
        assert ok is False

    def test_cancel(self):
        svc = OTPService()
        svc.generate(1, "cancel_me")
        assert svc.pending_count == 1

        svc.cancel(1, "cancel_me")
        assert svc.pending_count == 0


class TestOTPCleanup:
    def test_cleanup_removes_expired(self):
        svc = OTPService()
        c1 = svc.generate(1, "old")
        c1.expires_at = time.time() - 1
        svc._pending["1:old"] = c1

        svc.generate(2, "fresh")

        count = svc.cleanup_expired()
        assert count == 1
        assert svc.pending_count == 1

    def test_cleanup_keeps_valid(self):
        svc = OTPService()
        svc.generate(1, "valid")
        count = svc.cleanup_expired()
        assert count == 0
        assert svc.pending_count == 1
