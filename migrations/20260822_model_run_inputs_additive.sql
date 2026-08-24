-- Additive, review-only linkage from a model run to exact validated inputs.
-- Do not apply without explicit schema-change approval.

CREATE TABLE IF NOT EXISTS model_run_inputs (
    run_id TEXT NOT NULL,
    input_role TEXT NOT NULL CHECK (
        input_role IN ('MARKET_FEATURES', 'STOCK_UNIVERSE', 'STOCK_FUNDAMENTALS')
    ),
    snapshot_id TEXT NOT NULL,
    snapshot_checksum_sha256 TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, input_role),
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id),
    FOREIGN KEY (snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_model_run_inputs_snapshot
    ON model_run_inputs (snapshot_id, input_role);
