-- migration-id: 20260826_oracle_research_dataset_versions_additive
-- schema-version: 1
-- REVIEW-ONLY additive Turso migration for immutable Oracle research datasets.
-- DO NOT APPLY without explicit production schema approval, an approved writer,
-- a hash-locked migration plan, independent readback, and a rollback plan.
-- This artifact performs no inserts and does not freeze or promote any dataset.

-- statement: 001_dataset_versions
CREATE TABLE IF NOT EXISTS oracle_research_dataset_versions (
    dataset_version_id TEXT PRIMARY KEY,
    market_snapshot_id TEXT NOT NULL,
    market_snapshot_checksum_sha256 TEXT NOT NULL
        CHECK (LENGTH(market_snapshot_checksum_sha256) = 64),
    source_session_date TEXT NOT NULL,
    evidence_cutoff_utc TEXT NOT NULL,
    first_session_date TEXT NOT NULL,
    last_session_date TEXT NOT NULL,
    expected_row_count INTEGER NOT NULL CHECK (expected_row_count > 0),
    expected_ticker_count INTEGER NOT NULL CHECK (expected_ticker_count > 0),
    expected_session_count INTEGER NOT NULL CHECK (expected_session_count > 0),
    expected_provider_lineage_count INTEGER NOT NULL
        CHECK (expected_provider_lineage_count > 0),
    content_sha256 TEXT NOT NULL CHECK (LENGTH(content_sha256) = 64),
    ticker_universe_sha256 TEXT NOT NULL
        CHECK (LENGTH(ticker_universe_sha256) = 64),
    provider_lineage_sha256 TEXT NOT NULL
        CHECK (LENGTH(provider_lineage_sha256) = 64),
    schema_version TEXT NOT NULL,
    code_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('STAGING', 'FROZEN')),
    freeze_approval_id TEXT,
    frozen_by TEXT,
    frozen_at_utc TEXT,
    created_at_utc TEXT NOT NULL,
    CHECK (first_session_date <= last_session_date),
    CHECK (last_session_date = source_session_date),
    CHECK (
        (status = 'STAGING' AND freeze_approval_id IS NULL
            AND frozen_by IS NULL AND frozen_at_utc IS NULL)
        OR
        (status = 'FROZEN' AND freeze_approval_id IS NOT NULL
            AND frozen_by IS NOT NULL AND frozen_at_utc IS NOT NULL)
    ),
    FOREIGN KEY (market_snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);
-- end-statement

-- statement: 002_frozen_identity_index
CREATE UNIQUE INDEX IF NOT EXISTS idx_oracle_research_dataset_frozen_identity
    ON oracle_research_dataset_versions
       (market_snapshot_id, content_sha256, ticker_universe_sha256,
        provider_lineage_sha256)
    WHERE status = 'FROZEN';
-- end-statement

-- statement: 003_source_session_index
CREATE INDEX IF NOT EXISTS idx_oracle_research_dataset_source_session
    ON oracle_research_dataset_versions
       (source_session_date, status, evidence_cutoff_utc);
-- end-statement

-- statement: 004_provider_lineage
CREATE TABLE IF NOT EXISTS oracle_research_dataset_provider_lineage (
    dataset_version_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('YAHOO_FINANCE', 'TIINGO_EOD')),
    requested_source_session_date TEXT NOT NULL,
    first_available_date TEXT NOT NULL,
    last_available_date TEXT NOT NULL,
    source_row_count INTEGER NOT NULL CHECK (source_row_count > 0),
    source_checksum_sha256 TEXT NOT NULL
        CHECK (LENGTH(source_checksum_sha256) = 64),
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (dataset_version_id, ticker),
    CHECK (first_available_date <= last_available_date),
    CHECK (last_available_date = requested_source_session_date),
    FOREIGN KEY (dataset_version_id)
        REFERENCES oracle_research_dataset_versions(dataset_version_id)
);
-- end-statement

-- statement: 005_provider_binding_index
CREATE INDEX IF NOT EXISTS idx_oracle_research_provider_binding
    ON oracle_research_dataset_provider_lineage
       (dataset_version_id, provider, ticker);
-- end-statement

-- statement: 006_dataset_events
CREATE TABLE IF NOT EXISTS oracle_research_dataset_events (
    event_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('FREEZE', 'REVOKE')),
    market_snapshot_checksum_sha256 TEXT NOT NULL
        CHECK (LENGTH(market_snapshot_checksum_sha256) = 64),
    content_sha256 TEXT NOT NULL CHECK (LENGTH(content_sha256) = 64),
    ticker_universe_sha256 TEXT NOT NULL
        CHECK (LENGTH(ticker_universe_sha256) = 64),
    provider_lineage_sha256 TEXT NOT NULL
        CHECK (LENGTH(provider_lineage_sha256) = 64),
    actor TEXT NOT NULL,
    decided_at_utc TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (LENGTH(evidence_sha256) = 64),
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (dataset_version_id)
        REFERENCES oracle_research_dataset_versions(dataset_version_id)
);
-- end-statement

-- statement: 007_one_freeze_event_index
CREATE UNIQUE INDEX IF NOT EXISTS idx_oracle_research_one_freeze_event
    ON oracle_research_dataset_events (dataset_version_id)
    WHERE event_type = 'FREEZE';
-- end-statement

-- statement: 008_dataset_event_order_index
CREATE INDEX IF NOT EXISTS idx_oracle_research_dataset_event_order
    ON oracle_research_dataset_events
       (dataset_version_id, decided_at_utc, event_id);
-- end-statement

-- Frozen version metadata and its exact provider binding are append-only.
-- statement: 009_staging_insert_only
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_version_staging_insert_only
BEFORE INSERT ON oracle_research_dataset_versions
WHEN NEW.status <> 'STAGING'
BEGIN
    SELECT RAISE(ABORT, 'Oracle research datasets must be staged before freezing');
END;
-- end-statement

-- statement: 010_frozen_version_no_update
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_frozen_version_no_update
BEFORE UPDATE ON oracle_research_dataset_versions
WHEN OLD.status = 'FROZEN'
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research dataset is immutable');
END;
-- end-statement

-- statement: 011_version_no_delete
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_version_no_delete
BEFORE DELETE ON oracle_research_dataset_versions
BEGIN
    SELECT RAISE(ABORT, 'Oracle research dataset versions are append-only');
END;
-- end-statement

-- statement: 012_lineage_no_insert_after_freeze
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_lineage_no_insert_after_freeze
BEFORE INSERT ON oracle_research_dataset_provider_lineage
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE dataset_version_id = NEW.dataset_version_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research provider lineage is immutable');
END;
-- end-statement

-- statement: 013_lineage_no_update
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_lineage_no_update
BEFORE UPDATE ON oracle_research_dataset_provider_lineage
BEGIN
    SELECT RAISE(ABORT, 'Oracle research provider lineage is append-only');
END;
-- end-statement

-- statement: 014_lineage_no_delete
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_lineage_no_delete
BEFORE DELETE ON oracle_research_dataset_provider_lineage
BEGIN
    SELECT RAISE(ABORT, 'Oracle research provider lineage is append-only');
END;
-- end-statement

-- statement: 015_events_no_update
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_events_no_update
BEFORE UPDATE ON oracle_research_dataset_events
BEGIN
    SELECT RAISE(ABORT, 'Oracle research dataset events are append-only');
END;
-- end-statement

-- statement: 016_freeze_event_staging_only
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_freeze_event_staging_only
BEFORE INSERT ON oracle_research_dataset_events
WHEN NEW.event_type = 'FREEZE' AND NOT EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE dataset_version_id = NEW.dataset_version_id AND status = 'STAGING'
)
BEGIN
    SELECT RAISE(ABORT, 'Oracle research freeze event requires a staged dataset');
END;
-- end-statement

-- statement: 017_revoke_event_frozen_only
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_revoke_event_frozen_only
BEFORE INSERT ON oracle_research_dataset_events
WHEN NEW.event_type = 'REVOKE' AND NOT EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE dataset_version_id = NEW.dataset_version_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'Oracle research revocation requires a frozen dataset');
END;
-- end-statement

-- statement: 018_events_no_delete
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_events_no_delete
BEFORE DELETE ON oracle_research_dataset_events
BEGIN
    SELECT RAISE(ABORT, 'Oracle research dataset events are append-only');
END;
-- end-statement

-- Once a model-input snapshot is bound to a frozen research dataset, protect
-- the source metadata, feature rows, and provider lineage at the database edge.
-- statement: 019_source_metadata_no_update
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_source_metadata_no_update
BEFORE UPDATE ON model_input_snapshots
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id = OLD.snapshot_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research source metadata is immutable');
END;
-- end-statement

-- statement: 020_source_metadata_no_delete
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_source_metadata_no_delete
BEFORE DELETE ON model_input_snapshots
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id = OLD.snapshot_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research source metadata is immutable');
END;
-- end-statement

-- statement: 021_feature_no_insert
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_feature_no_insert
BEFORE INSERT ON market_daily_features
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id = NEW.snapshot_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research feature rows are immutable');
END;
-- end-statement

-- statement: 022_feature_no_update
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_feature_no_update
BEFORE UPDATE ON market_daily_features
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id IN (OLD.snapshot_id, NEW.snapshot_id)
      AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research feature rows are immutable');
END;
-- end-statement

-- statement: 023_feature_no_delete
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_feature_no_delete
BEFORE DELETE ON market_daily_features
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id = OLD.snapshot_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research feature rows are immutable');
END;
-- end-statement

-- statement: 024_source_lineage_no_insert
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_source_lineage_no_insert
BEFORE INSERT ON market_data_provider_lineage
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id = NEW.snapshot_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research source lineage is immutable');
END;
-- end-statement

-- statement: 025_source_lineage_no_update
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_source_lineage_no_update
BEFORE UPDATE ON market_data_provider_lineage
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id IN (OLD.snapshot_id, NEW.snapshot_id)
      AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research source lineage is immutable');
END;
-- end-statement

-- statement: 026_source_lineage_no_delete
CREATE TRIGGER IF NOT EXISTS trg_oracle_research_source_lineage_no_delete
BEFORE DELETE ON market_data_provider_lineage
WHEN EXISTS (
    SELECT 1 FROM oracle_research_dataset_versions
    WHERE market_snapshot_id = OLD.snapshot_id AND status = 'FROZEN'
)
BEGIN
    SELECT RAISE(ABORT, 'frozen Oracle research source lineage is immutable');
END;
-- end-statement
