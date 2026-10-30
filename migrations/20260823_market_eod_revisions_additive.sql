-- Additive, review-only Turso migration for provider-native EOD evidence.
-- Do not apply until the provider adapters, resumable writer, and audits pass.
-- No existing market, model, recommendation, ledger, or order row is modified.

CREATE TABLE IF NOT EXISTS market_eod_ingestion_runs (
    run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (
        provider IN ('ALPACA_MARKET_DATA', 'TIINGO_EOD', 'YAHOO_FINANCE')
    ),
    ingestion_mode TEXT NOT NULL CHECK (
        ingestion_mode IN ('HISTORICAL_BASELINE', 'DAILY_DELTA', 'CORPORATE_ACTION_REFRESH')
    ),
    requested_source_session_date TEXT NOT NULL,
    available_at_utc TEXT NOT NULL,
    code_version_sha256 TEXT NOT NULL,
    expected_ticker_count INTEGER NOT NULL CHECK (expected_ticker_count > 0),
    status TEXT NOT NULL CHECK (status IN ('STAGING', 'COMPLETE', 'REJECTED')),
    status_notes TEXT,
    created_at_utc TEXT NOT NULL,
    completed_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_market_eod_ingestion_runs_lookup
    ON market_eod_ingestion_runs (
        provider, requested_source_session_date, status, available_at_utc
    );

CREATE TABLE IF NOT EXISTS market_eod_bar_revisions (
    run_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (
        provider IN ('ALPACA_MARKET_DATA', 'TIINGO_EOD', 'YAHOO_FINANCE')
    ),
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    raw_open REAL NOT NULL,
    raw_high REAL NOT NULL,
    raw_low REAL NOT NULL,
    raw_close REAL NOT NULL,
    raw_volume REAL NOT NULL CHECK (raw_volume >= 0),
    adjusted_open REAL,
    adjusted_high REAL,
    adjusted_low REAL,
    adjusted_close REAL,
    adjusted_volume REAL,
    dividend_cash REAL NOT NULL DEFAULT 0.0,
    split_factor REAL NOT NULL DEFAULT 1.0 CHECK (split_factor > 0),
    source_value_sha256 TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, ticker, date),
    FOREIGN KEY (run_id) REFERENCES market_eod_ingestion_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_market_eod_bar_revisions_lookup
    ON market_eod_bar_revisions (provider, ticker, date, observed_at_utc);
