-- Additive, review-only instrument governance for market/model inputs.
-- Do not apply or populate until the exact registry proposal is owner-approved.

CREATE TABLE IF NOT EXISTS market_instrument_registry_versions (
    registry_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'SUPERSEDED')),
    evidence_as_of_date TEXT NOT NULL,
    source_evidence_sha256 TEXT NOT NULL,
    source_evidence_json TEXT NOT NULL,
    approved_by TEXT,
    approved_at_utc TEXT,
    created_at_utc TEXT NOT NULL,
    CHECK (
        (status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at_utc IS NOT NULL)
        OR status IN ('DRAFT', 'SUPERSEDED')
    )
);

CREATE INDEX IF NOT EXISTS idx_market_registry_versions_status
    ON market_instrument_registry_versions (status, evidence_as_of_date);

CREATE TABLE IF NOT EXISTS market_instrument_registry (
    registry_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    asset_class TEXT NOT NULL CHECK (asset_class IN ('STOCK', 'ETF', 'MACRO')),
    sector TEXT,
    usage TEXT NOT NULL CHECK (
        usage IN ('MODEL_CANDIDATE', 'VALUATION_ONLY', 'BENCHMARK', 'QUARANTINED')
    ),
    minimum_history_rows INTEGER NOT NULL CHECK (minimum_history_rows > 0),
    classification_reason TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (registry_id, ticker),
    FOREIGN KEY (registry_id) REFERENCES market_instrument_registry_versions(registry_id)
);

CREATE INDEX IF NOT EXISTS idx_market_instrument_registry_usage
    ON market_instrument_registry (registry_id, asset_class, usage, ticker);
