-- Additive, review-only approval evidence for immutable model-input snapshots.
-- Do not apply without explicit schema-change approval. No existing record is
-- updated or deleted by this migration.

CREATE TABLE IF NOT EXISTS model_input_approval_events (
    event_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED', 'REVOKED')),
    approved_by TEXT NOT NULL,
    decided_at_utc TEXT NOT NULL,
    snapshot_checksum_sha256 TEXT NOT NULL,
    source_evidence_type TEXT NOT NULL CHECK (
        source_evidence_type IN ('PREDICTIVE_SCREENING', 'MANUAL_RESEARCH_REVIEW')
    ),
    source_evidence_id TEXT NOT NULL,
    approval_notes TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_model_input_approval_effective
    ON model_input_approval_events (snapshot_id, decided_at_utc, event_id);
