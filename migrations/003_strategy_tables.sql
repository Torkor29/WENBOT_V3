-- Migration 003: Strategy tables (fusion with Dirto copybot)
-- Applied automatically by bot/db/session.py on startup.
-- This file is for reference / manual deployment only.

-- ═══ New tables ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS strategies (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    docker_image VARCHAR(256) DEFAULT '',
    version VARCHAR(16) DEFAULT '1.0.0',
    status VARCHAR(8) DEFAULT 'testing',
    visibility VARCHAR(8) DEFAULT 'private',
    markets JSON,
    min_trade_size FLOAT DEFAULT 2.0,
    max_trade_size FLOAT DEFAULT 10.0,
    execution_delay_ms INTEGER DEFAULT 100,
    total_trades INTEGER DEFAULT 0,
    total_pnl FLOAT DEFAULT 0.0,
    win_rate FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_id VARCHAR(64) NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    trade_size FLOAT DEFAULT 4.0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, strategy_id)
);
CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_strategy_id ON subscriptions(strategy_id);

CREATE TABLE IF NOT EXISTS strategy_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id VARCHAR(64) NOT NULL REFERENCES strategies(id),
    action VARCHAR(8) NOT NULL,
    side VARCHAR(8) NOT NULL,
    market_slug VARCHAR(512) NOT NULL,
    token_id VARCHAR(256) NOT NULL,
    max_price FLOAT DEFAULT 0.0,
    shares FLOAT DEFAULT 0.0,
    confidence FLOAT DEFAULT 0.0,
    subscribers_count INTEGER DEFAULT 0,
    executed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    total_volume FLOAT DEFAULT 0.0,
    signal_timestamp FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_strategy_signals_strategy_id ON strategy_signals(strategy_id);
CREATE INDEX IF NOT EXISTS ix_strategy_signals_created ON strategy_signals(created_at);

CREATE TABLE IF NOT EXISTS daily_performance_fees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fee_date DATE NOT NULL,
    total_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    total_pnl FLOAT DEFAULT 0.0,
    perf_fee_rate FLOAT DEFAULT 0.05,
    perf_fee_amount FLOAT DEFAULT 0.0,
    perf_fee_tx_hash VARCHAR(128),
    status VARCHAR(8) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, fee_date)
);
CREATE INDEX IF NOT EXISTS ix_daily_perf_fees_user_id ON daily_performance_fees(user_id);

CREATE TABLE IF NOT EXISTS strategy_user_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    trade_fee_rate FLOAT DEFAULT 0.01,
    max_trades_per_day INTEGER DEFAULT 50,
    trades_today INTEGER DEFAULT 0,
    trades_today_reset_date DATE,
    is_paused BOOLEAN DEFAULT false,
    matic_refills_count INTEGER DEFAULT 0,
    matic_total_sent FLOAT DEFAULT 0.0,
    last_matic_refill_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ═══ ALTER existing tables ═══════════════════════════════════════════

-- Users: strategy wallet
ALTER TABLE users ADD COLUMN strategy_wallet_address VARCHAR(255);
ALTER TABLE users ADD COLUMN encrypted_strategy_private_key BLOB;
ALTER TABLE users ADD COLUMN strategy_wallet_auto_created BOOLEAN DEFAULT false;

-- Trades: strategy fields
ALTER TABLE trades ADD COLUMN strategy_id VARCHAR(64) REFERENCES strategies(id);
ALTER TABLE trades ADD COLUMN result VARCHAR(8);
ALTER TABLE trades ADD COLUMN pnl FLOAT;
ALTER TABLE trades ADD COLUMN resolved_at TIMESTAMP;
ALTER TABLE trades ADD COLUMN strategy_fee_rate FLOAT;
ALTER TABLE trades ADD COLUMN strategy_fee_amount FLOAT;
ALTER TABLE trades ADD COLUMN strategy_fee_tx_hash VARCHAR(128);
ALTER TABLE trades ADD COLUMN execution_priority INTEGER;
CREATE INDEX IF NOT EXISTS ix_trades_strategy_id ON trades(strategy_id);

-- GroupConfig: strategy topics
ALTER TABLE group_config ADD COLUMN topic_strategies_id INTEGER;
ALTER TABLE group_config ADD COLUMN topic_strategies_perf_id INTEGER;
