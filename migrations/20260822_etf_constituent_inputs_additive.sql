-- Additive, review-only DB input contract for dated ETF constituent weights.
-- Do not apply without explicit schema-change approval.

CREATE TABLE IF NOT EXISTS etf_constituent_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_session_date TEXT NOT NULL,
    available_at_utc TEXT NOT NULL,
    provider TEXT NOT NULL,
    code_version TEXT NOT NULL,
    source_checksum_sha256 TEXT NOT NULL,
    expected_row_count INTEGER NOT NULL CHECK (expected_row_count > 0),
    expected_etf_count INTEGER NOT NULL CHECK (expected_etf_count > 0),
    status TEXT NOT NULL CHECK (status IN ('STAGING', 'VALIDATED', 'REJECTED')),
    validation_notes TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_etf_constituent_snapshot_lookup
    ON etf_constituent_snapshots (source_session_date, status, available_at_utc);

CREATE TABLE IF NOT EXISTS etf_constituent_weights (
    snapshot_id TEXT NOT NULL,
    etf_ticker TEXT NOT NULL,
    constituent_ticker TEXT NOT NULL,
    constituent_rank INTEGER NOT NULL CHECK (constituent_rank > 0),
    constituent_weight REAL NOT NULL CHECK (
        constituent_weight > 0.0 AND constituent_weight <= 1.0
    ),
    effective_date TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, etf_ticker, constituent_ticker),
    UNIQUE (snapshot_id, etf_ticker, constituent_rank),
    FOREIGN KEY (snapshot_id) REFERENCES etf_constituent_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_etf_constituent_weights_read
    ON etf_constituent_weights (snapshot_id, etf_ticker, constituent_rank);
