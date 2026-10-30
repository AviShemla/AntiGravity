-- Additive, review-only Turso migration.
-- Do not apply until writer/read-path tests and rollback evidence are approved.
-- No existing table, record, or pending order is modified by this migration.

CREATE TABLE IF NOT EXISTS model_runs (
    run_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    asset_class TEXT NOT NULL CHECK (asset_class IN ('STOCK', 'ETF', 'ARENA')),
    prediction_date TEXT NOT NULL,
    source_session_date TEXT NOT NULL,
    as_of_timestamp_utc TEXT NOT NULL,
    code_version TEXT NOT NULL,
    config_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('STARTED', 'COMPLETED', 'QUARANTINED', 'FAILED')),
    failure_reason TEXT,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_runs_prediction
    ON model_runs (asset_class, prediction_date, status);

CREATE TABLE IF NOT EXISTS model_scorecards (
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    persona TEXT NOT NULL,
    posterior_probability REAL,
    posterior_probability_std REAL,
    posterior_probability_q05 REAL,
    posterior_probability_q95 REAL,
    expected_return REAL,
    expected_return_std REAL,
    expected_risk REAL,
    recommendation TEXT NOT NULL CHECK (recommendation IN ('BUY', 'SELL', 'HOLD', 'NO_TRADE')),
    proposed_allocation REAL,
    quarantine_reason TEXT,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, ticker, persona),
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_model_scorecards_lookup
    ON model_scorecards (ticker, persona);

CREATE TABLE IF NOT EXISTS etf_prior_lineage (
    prior_id TEXT PRIMARY KEY,
    etf_run_id TEXT NOT NULL,
    prior_type TEXT NOT NULL CHECK (prior_type IN ('STOCK_POSTERIOR', 'SECTOR_AGGREGATE', 'WHALE_FUNDAMENTAL', 'ETF_TECHNICAL', 'MACRO')),
    source_run_id TEXT,
    source_ticker TEXT,
    source_session_date TEXT NOT NULL,
    available_at_utc TEXT NOT NULL,
    constituent_weight REAL,
    transformed_value REAL NOT NULL,
    prior_sigma REAL NOT NULL,
    transformation TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (etf_run_id) REFERENCES model_runs(run_id),
    FOREIGN KEY (source_run_id) REFERENCES model_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_etf_prior_lineage_run
    ON etf_prior_lineage (etf_run_id, prior_type);

CREATE TABLE IF NOT EXISTS etf_universe_decisions (
    decision_id TEXT PRIMARY KEY,
    etf_run_id TEXT NOT NULL,
    persona TEXT NOT NULL,
    incumbent_ticker TEXT,
    candidate_ticker TEXT,
    decision TEXT NOT NULL CHECK (decision IN ('RETAIN', 'REPLACE', 'CASH')),
    expected_net_benefit REAL,
    expected_turnover_cost REAL,
    risk_gate_passed INTEGER NOT NULL CHECK (risk_gate_passed IN (0, 1)),
    evidence_gate_passed INTEGER NOT NULL CHECK (evidence_gate_passed IN (0, 1)),
    refusal_reason TEXT,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (etf_run_id) REFERENCES model_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_etf_universe_decisions_run
    ON etf_universe_decisions (etf_run_id, persona);
