-- Migration 004: slippage tolerance + activity-based tracking
--
-- Context: for fast-moving markets (BTC 5min), FOK orders get rejected because
-- orderbook moves faster than detection latency. A limit price with slippage
-- tolerance lets FOK/FAK fills succeed even when price drifted a bit.
--
-- Also: monitor now tracks last_activity_ts per wallet in memory (no DB column
-- needed for that). max_slippage_bps is user-configurable.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS max_slippage_bps INTEGER DEFAULT 300;

-- Commentaire indicatif :
--   max_slippage_bps = slippage maximum toléré pour les market orders, en bps
--   (basis points, 1 bps = 0.01 %). Défaut 300 = 3 %.
--   BTC 5m / scalping : garder 200-500 bps.
--   Markets long terme : 50-100 bps suffisent.
--   0 = exige match exact au prix du signal (FOK strict, quasi garanti de fail).
