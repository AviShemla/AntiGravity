-- Additive, review-only Turso migration.
-- Do not apply until the provider-chain writer and audit tests are approved.
-- No existing snapshot, market row, recommendation, or order is modified.

CREATE TABLE IF NOT EXISTS market_data_provider_lineage (
    snapshot_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('YAHOO_FINANCE', 'TIINGO_EOD')),
    requested_source_session_date TEXT NOT NULL,
    first_available_date TEXT NOT NULL,
    last_available_date TEXT NOT NULL,
    source_row_count INTEGER NOT NULL CHECK (source_row_count > 0),
    source_checksum_sha256 TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, ticker),
    FOREIGN KEY (snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_market_provider_lineage_lookup
    ON market_data_provider_lineage (snapshot_id, provider, ticker);
