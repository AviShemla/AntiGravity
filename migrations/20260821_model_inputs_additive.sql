-- Additive Turso schema for versioned, database-only model inputs.
-- Existing ledgers, orders, scorecards, and legacy price rows are untouched.

CREATE TABLE IF NOT EXISTS model_input_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    dataset_type TEXT NOT NULL CHECK (
        dataset_type IN ('MARKET_FEATURES', 'STOCK_UNIVERSE', 'STOCK_FUNDAMENTALS')
    ),
    source_session_date TEXT NOT NULL,
    available_at_utc TEXT NOT NULL,
    provider TEXT NOT NULL,
    code_version TEXT NOT NULL,
    source_checksum_sha256 TEXT,
    expected_row_count INTEGER NOT NULL CHECK (expected_row_count >= 0),
    expected_ticker_count INTEGER NOT NULL CHECK (expected_ticker_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('STAGING', 'VALIDATED', 'REJECTED')),
    validation_notes TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_input_snapshots_lookup
    ON model_input_snapshots (dataset_type, source_session_date, status, available_at_utc);

CREATE TABLE IF NOT EXISTS stock_universe_config (
    snapshot_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    selection_rank INTEGER NOT NULL CHECK (selection_rank > 0),
    oos_accuracy REAL,
    causal_depth INTEGER NOT NULL CHECK (causal_depth BETWEEN 1 AND 5),
    lag1_ticker TEXT NOT NULL,
    lag2_ticker TEXT,
    lag3_ticker TEXT,
    lag4_ticker TEXT,
    lag5_ticker TEXT,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    PRIMARY KEY (snapshot_id, ticker),
    UNIQUE (snapshot_id, selection_rank),
    FOREIGN KEY (snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_universe_config_active
    ON stock_universe_config (snapshot_id, active, selection_rank);

CREATE TABLE IF NOT EXISTS stock_fundamental_features (
    snapshot_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    profit_margin REAL,
    debt_to_equity REAL,
    analyst_recommendation REAL,
    analyst_target REAL,
    fundamental_score REAL NOT NULL,
    PRIMARY KEY (snapshot_id, ticker),
    FOREIGN KEY (snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_fundamental_features_ticker
    ON stock_fundamental_features (ticker, as_of_date);

CREATE TABLE IF NOT EXISTS market_daily_features (
    snapshot_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    sector TEXT,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL NOT NULL,
    adjusted_close REAL,
    volume REAL,
    dividends REAL,
    stock_splits REAL,
    daily_return_pct REAL,
    daily_stdev REAL,
    stdev_5d REAL,
    stdev_10d REAL,
    stdev_20d REAL,
    max_high_20d REAL,
    min_low_20d REAL,
    rsi_14d REAL,
    atr_14d REAL,
    plus_di_14d REAL,
    minus_di_14d REAL,
    adx_14d REAL,
    dynamic_stop_loss REAL,
    ras_signal TEXT,
    analyst_consensus TEXT,
    analyst_upside_pct REAL,
    sector_momentum_score REAL,
    sector_regime TEXT,
    vix_close REAL,
    market_fear_level TEXT,
    tnx_close REAL,
    tnx_lag1_return REAL,
    tnx_trend_5d REAL,
    PRIMARY KEY (snapshot_id, ticker, date),
    FOREIGN KEY (snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_market_daily_features_model_read
    ON market_daily_features (snapshot_id, date, ticker);
