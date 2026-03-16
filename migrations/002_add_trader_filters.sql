-- Add per-trader category filters column
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS trader_filters JSON DEFAULT '{}';
