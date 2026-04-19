-- Add shares and received columns to trades table (for BUY/SELL tracking)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS shares FLOAT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS received FLOAT;

-- Add signal_timestamp to strategy_signals
ALTER TABLE strategy_signals ADD COLUMN IF NOT EXISTS signal_timestamp FLOAT;

-- Insert test strategy
INSERT INTO strategies (id, name, description, docker_image, status, visibility, execution_delay_ms)
VALUES ('strat_test_v1', 'Test Strategy', 'Signaux simulés toutes les 60s pour tester le flow', 'local', 'active', 'public', 100)
ON CONFLICT (id) DO NOTHING;
