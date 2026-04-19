#!/usr/bin/env python3
"""
Test strategy simulator — publishes fake trading signals to Redis.

Publishes a signal every 60s on channel `signals:strat_test_v1`.
Alternates randomly between BUY (70%) and SELL (30%).

Usage:
    python3 scripts/test_strategy.py
"""

import json
import math
import os
import random
import signal
import sys
import time

import redis
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

REDIS_URL = os.getenv("TEST_REDIS_URL", os.getenv("REDIS_URL", "redis://localhost:30379"))
STRATEGY_ID = "strat_test_v1"
CHANNEL = f"signals:{STRATEGY_ID}"
INTERVAL = 60  # seconds

ASSETS = ["btc", "eth", "sol", "matic", "doge", "avax", "link", "ada"]

# Track last BUY side so SELL uses the same side
_last_buy_side = "YES"
_running = True


def _signal_handler(signum, frame):
    global _running
    print(f"\n[{_ts()}] Ctrl+C received, stopping...")
    _running = False


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _next_5min_window() -> int:
    """Return the unix timestamp of the next 5-minute window boundary."""
    now = time.time()
    return int(math.ceil(now / 300) * 300)


def _random_token_id() -> str:
    return os.urandom(32).hex()


def _make_signal() -> dict:
    global _last_buy_side

    action = "BUY" if random.random() < 0.70 else "SELL"
    asset = random.choice(ASSETS)
    window_ts = _next_5min_window()
    market_slug = f"{asset}-updown-5m-{window_ts}"
    token_id = _random_token_id()

    if action == "BUY":
        side = random.choice(["YES", "NO"])
        _last_buy_side = side
        max_price = round(random.uniform(0.55, 0.85), 2)
        shares = 0.0
    else:
        side = _last_buy_side
        max_price = 0.0
        shares = round(random.uniform(2.0, 8.0), 1)

    return {
        "strategy_id": STRATEGY_ID,
        "action": action,
        "side": side,
        "market_slug": market_slug,
        "token_id": token_id,
        "max_price": max_price,
        "shares": shares,
        "confidence": round(random.uniform(0.60, 0.95), 2),
        "timestamp": time.time(),
    }


def main():
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print(f"[{_ts()}] Connecting to Redis: {REDIS_URL}")
    r = redis.from_url(REDIS_URL, decode_responses=True)

    try:
        r.ping()
        print(f"[{_ts()}] Redis connected. Publishing to '{CHANNEL}' every {INTERVAL}s")
    except redis.ConnectionError as e:
        print(f"[{_ts()}] Failed to connect to Redis: {e}")
        sys.exit(1)

    print(f"[{_ts()}] Press Ctrl+C to stop\n")

    while _running:
        sig = _make_signal()
        payload = json.dumps(sig)

        receivers = r.publish(CHANNEL, payload)

        action_str = sig["action"]
        if action_str == "BUY":
            detail = f"side={sig['side']} max_price={sig['max_price']}"
        else:
            detail = f"side={sig['side']} shares={sig['shares']}"

        print(
            f"[{_ts()}] {action_str} | {sig['market_slug']} | {detail} "
            f"| confidence={sig['confidence']} | receivers={receivers}"
        )

        # Sleep in small increments for responsive Ctrl+C
        for _ in range(INTERVAL):
            if not _running:
                break
            time.sleep(1)

    print(f"[{_ts()}] Stopped.")


if __name__ == "__main__":
    main()
