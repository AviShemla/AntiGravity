-- Additive evidence schema for leakage-resistant predictive lead/lag screening.
-- The term "causal" is deliberately avoided: observational lag association is
-- not causal identification. No legacy tables or rows are modified.

CREATE TABLE IF NOT EXISTS predictive_screening_runs (
    screening_run_id TEXT PRIMARY KEY,
    market_snapshot_id TEXT NOT NULL,
    source_session_date TEXT NOT NULL,
    cutoff_utc TEXT NOT NULL,
    code_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'VALIDATED', 'REJECTED', 'FAILED')),
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    validation_notes TEXT,
    FOREIGN KEY (market_snapshot_id) REFERENCES model_input_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_predictive_screening_runs_status
    ON predictive_screening_runs (source_session_date, status, cutoff_utc);

CREATE TABLE IF NOT EXISTS predictive_screening_results (
    screening_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    eligible INTEGER NOT NULL CHECK (eligible IN (0, 1)),
    rejection_reason TEXT,
    oos_sessions INTEGER NOT NULL CHECK (oos_sessions >= 0),
    oos_accuracy REAL,
    accuracy_ci_low REAL,
    accuracy_ci_high REAL,
    brier_score REAL,
    log_loss REAL,
    calibration_error REAL,
    majority_accuracy REAL,
    own_lag_accuracy REAL,
    own_lag_brier REAL,
    selected_depth INTEGER CHECK (selected_depth BETWEEN 1 AND 5),
    lag1_ticker TEXT,
    lag2_ticker TEXT,
    lag3_ticker TEXT,
    lag4_ticker TEXT,
    lag5_ticker TEXT,
    feature_spec_json TEXT,
    PRIMARY KEY (screening_run_id, ticker),
    FOREIGN KEY (screening_run_id) REFERENCES predictive_screening_runs(screening_run_id)
);

CREATE INDEX IF NOT EXISTS idx_predictive_screening_results_eligible
    ON predictive_screening_results (screening_run_id, eligible, brier_score, ticker);

CREATE TABLE IF NOT EXISTS predictive_screening_fold_metrics (
    screening_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    fold_number INTEGER NOT NULL CHECK (fold_number > 0),
    train_start_date TEXT NOT NULL,
    train_end_date TEXT NOT NULL,
    test_start_date TEXT NOT NULL,
    test_end_date TEXT NOT NULL,
    purge_sessions INTEGER NOT NULL CHECK (purge_sessions >= 0),
    test_sessions INTEGER NOT NULL CHECK (test_sessions > 0),
    accuracy REAL NOT NULL,
    brier_score REAL NOT NULL,
    log_loss REAL NOT NULL,
    majority_accuracy REAL NOT NULL,
    own_lag_accuracy REAL NOT NULL,
    own_lag_brier REAL NOT NULL,
    selected_depth INTEGER NOT NULL CHECK (selected_depth BETWEEN 1 AND 5),
    feature_spec_json TEXT NOT NULL,
    PRIMARY KEY (screening_run_id, ticker, fold_number),
    FOREIGN KEY (screening_run_id, ticker)
        REFERENCES predictive_screening_results(screening_run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_predictive_screening_fold_metrics_run
    ON predictive_screening_fold_metrics (screening_run_id, ticker, fold_number);
