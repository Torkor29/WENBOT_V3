-- Users
CREATE TABLE users (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    telegram_id BIGINT UNIQUE NOT NULL,
    telegram_username TEXT,
    wallet_address TEXT NOT NULL,
    encrypted_private_key TEXT NOT NULL,
    trade_fee_rate FLOAT DEFAULT 0.01 CHECK (trade_fee_rate >= 0.01),
    is_active BOOLEAN DEFAULT true,
    max_trade_size FLOAT DEFAULT 4.0,
    max_trades_per_day INTEGER DEFAULT 50,
    is_paused BOOLEAN DEFAULT false,
    matic_refills_count INTEGER DEFAULT 0,
    matic_total_sent FLOAT DEFAULT 0,
    last_matic_refill_at TIMESTAMPTZ,
    trades_today INTEGER DEFAULT 0,
    trades_today_reset_at DATE DEFAULT CURRENT_DATE
);

-- Strategies
CREATE TABLE strategies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    docker_image TEXT NOT NULL,
    version TEXT DEFAULT '1.0.0',
    status TEXT DEFAULT 'testing' CHECK (status IN ('active', 'paused', 'testing')),
    visibility TEXT DEFAULT 'private' CHECK (visibility IN ('public', 'private')),
    markets JSONB DEFAULT '[]'::jsonb,
    min_trade_size FLOAT DEFAULT 2.0,
    max_trade_size FLOAT DEFAULT 10.0,
    execution_delay_ms INTEGER DEFAULT 100,
    track_record_since TIMESTAMPTZ,
    total_trades INTEGER DEFAULT 0,
    total_pnl FLOAT DEFAULT 0,
    win_rate FLOAT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Subscriptions (user × strategy)
CREATE TABLE subscriptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    strategy_id TEXT REFERENCES strategies(id) ON DELETE CASCADE,
    trade_size FLOAT NOT NULL CHECK (trade_size >= 1.0),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, strategy_id)
);

-- Trades
CREATE TABLE trades (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    user_id UUID REFERENCES users(id),
    strategy_id TEXT REFERENCES strategies(id),
    market_slug TEXT NOT NULL,
    token_id TEXT,
    direction TEXT,
    side TEXT CHECK (side IN ('YES', 'NO')),
    entry_price FLOAT,
    amount_usdc FLOAT,
    trade_fee_rate FLOAT,
    trade_fee_amount FLOAT,
    trade_fee_tx_hash TEXT,
    order_tx_hash TEXT,
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PLACED', 'FILLED', 'FAILED', 'SKIPPED')),
    result TEXT CHECK (result IN ('WON', 'LOST', NULL)),
    pnl FLOAT,
    execution_priority INTEGER,
    execution_delay_ms INTEGER,
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_trades_user ON trades(user_id);
CREATE INDEX idx_trades_strategy ON trades(strategy_id);
CREATE INDEX idx_trades_created ON trades(created_at);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_market ON trades(market_slug);

-- Daily performance fees
CREATE TABLE daily_performance_fees (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    user_id UUID REFERENCES users(id),
    date DATE NOT NULL,
    total_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    total_pnl FLOAT,
    perf_fee_rate FLOAT DEFAULT 0.05,
    perf_fee_amount FLOAT,
    perf_fee_tx_hash TEXT,
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SENT', 'SKIPPED', 'FAILED')),
    UNIQUE(user_id, date)
);

-- Strategy signals (audit trail)
CREATE TABLE strategy_signals (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    strategy_id TEXT REFERENCES strategies(id),
    action TEXT NOT NULL,
    side TEXT,
    market_slug TEXT NOT NULL,
    token_id TEXT,
    max_price FLOAT,
    confidence FLOAT,
    subscribers_count INTEGER DEFAULT 0,
    executed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    total_volume FLOAT DEFAULT 0
);

CREATE INDEX idx_signals_strategy ON strategy_signals(strategy_id);
CREATE INDEX idx_signals_created ON strategy_signals(created_at);

-- Admin alerts log
CREATE TABLE admin_alerts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    alert_type TEXT NOT NULL,
    severity TEXT DEFAULT 'info' CHECK (severity IN ('info', 'warning', 'critical')),
    message TEXT NOT NULL,
    user_id UUID REFERENCES users(id),
    metadata JSONB DEFAULT '{}'::jsonb,
    acknowledged BOOLEAN DEFAULT false
);
