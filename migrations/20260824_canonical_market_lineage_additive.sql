-- Additive, review-only Turso migration for canonical EOD and feature lineage.
-- Do not apply until the writer, read path, rollback plan, and owner approval
-- are recorded. This migration modifies no existing row or table.

CREATE TABLE IF NOT EXISTS market_canonical_policies (
    policy_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    provider_priority_json TEXT NOT NULL,
    evidence_cutoff_rule TEXT NOT NULL,
    code_version TEXT NOT NULL,
    approved_by TEXT,
    approved_at_utc TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_canonical_policy_approved
    ON market_canonical_policies (status)
    WHERE status = 'APPROVED';

CREATE TABLE IF NOT EXISTS market_canonical_bar_snapshots (
    canonical_snapshot_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    parent_canonical_snapshot_id TEXT,
    source_session_date TEXT NOT NULL,
    evidence_cutoff_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('STAGING', 'VALIDATED', 'FAILED')),
    expected_key_count INTEGER NOT NULL CHECK (expected_key_count >= 0),
    actual_key_count INTEGER CHECK (actual_key_count >= 0),
    content_sha256 TEXT,
    validation_evidence TEXT,
    created_at_utc TEXT NOT NULL,
    validated_at_utc TEXT,
    FOREIGN KEY (policy_id) REFERENCES market_canonical_policies(policy_id),
    FOREIGN KEY (parent_canonical_snapshot_id)
        REFERENCES market_canonical_bar_snapshots(canonical_snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_market_canonical_snapshot_lookup
    ON market_canonical_bar_snapshots
       (source_session_date, status, evidence_cutoff_utc);

CREATE TABLE IF NOT EXISTS market_canonical_bars (
    canonical_snapshot_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    raw_open REAL NOT NULL,
    raw_high REAL NOT NULL,
    raw_low REAL NOT NULL,
    raw_close REAL NOT NULL,
    raw_volume REAL NOT NULL,
    adjusted_open REAL,
    adjusted_high REAL,
    adjusted_low REAL,
    adjusted_close REAL NOT NULL,
    adjusted_volume REAL,
    dividend_cash REAL NOT NULL,
    split_factor REAL NOT NULL,
    source_value_sha256 TEXT NOT NULL,
    canonical_provider TEXT NOT NULL,
    canonical_run_id TEXT NOT NULL,
    canonical_observed_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (canonical_snapshot_id, ticker, date),
    FOREIGN KEY (canonical_snapshot_id)
        REFERENCES market_canonical_bar_snapshots(canonical_snapshot_id),
    FOREIGN KEY (canonical_run_id)
        REFERENCES market_eod_ingestion_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_market_canonical_bar_model_read
    ON market_canonical_bars (canonical_snapshot_id, date, ticker);

CREATE TABLE IF NOT EXISTS market_feature_recompute_runs (
    recompute_run_id TEXT PRIMARY KEY,
    canonical_snapshot_id TEXT NOT NULL,
    parent_market_snapshot_id TEXT NOT NULL,
    output_market_snapshot_id TEXT,
    first_changed_session TEXT NOT NULL,
    planned_key_count INTEGER NOT NULL CHECK (planned_key_count > 0),
    actual_key_count INTEGER CHECK (actual_key_count >= 0),
    patch_content_sha256 TEXT NOT NULL,
    code_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('PLANNED', 'STAGING', 'VALIDATED', 'FAILED')
    ),
    validation_evidence TEXT,
    created_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    FOREIGN KEY (canonical_snapshot_id)
        REFERENCES market_canonical_bar_snapshots(canonical_snapshot_id),
    FOREIGN KEY (parent_market_snapshot_id)
        REFERENCES model_input_snapshots(snapshot_id),
    FOREIGN KEY (output_market_snapshot_id)
        REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_market_feature_recompute_lookup
    ON market_feature_recompute_runs
       (canonical_snapshot_id, parent_market_snapshot_id, status);

CREATE TABLE IF NOT EXISTS market_feature_recompute_keys (
    recompute_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    recompute_scope TEXT NOT NULL CHECK (
        recompute_scope IN ('TICKER_LOCAL', 'CROSS_MARKET', 'BOTH')
    ),
    PRIMARY KEY (recompute_run_id, ticker, date),
    FOREIGN KEY (recompute_run_id)
        REFERENCES market_feature_recompute_runs(recompute_run_id)
);

CREATE INDEX IF NOT EXISTS idx_market_feature_recompute_keys_session
    ON market_feature_recompute_keys (recompute_run_id, date, ticker);
