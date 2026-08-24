-- Additive, review-only Turso migration for per-prediction policy comparison.
-- It authorizes no recommendation, allocation, pending order, or execution.
-- Do not apply until the writer/readback path and owner review are complete.

CREATE TABLE IF NOT EXISTS stock_prediction_decision_audits (
    audit_id TEXT PRIMARY KEY,
    model_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    persona TEXT NOT NULL,
    resolved_base_persona TEXT NOT NULL,
    probability_up_mean REAL NOT NULL,
    probability_up_q05 REAL NOT NULL,
    probability_up_q95 REAL NOT NULL,
    expected_return REAL NOT NULL,
    expected_risk REAL NOT NULL,
    round_trip_cost REAL NOT NULL,
    vix_close REAL NOT NULL,
    raw_model_signal TEXT NOT NULL CHECK (
        raw_model_signal IN ('BUY', 'SELL', 'HOLD', 'NO_TRADE')
    ),
    ag_action TEXT NOT NULL CHECK (
        ag_action IN ('BUY', 'SELL', 'HOLD', 'NO_TRADE')
    ),
    codex_action TEXT NOT NULL CHECK (
        codex_action IN ('BUY', 'SELL', 'HOLD', 'NO_TRADE')
    ),
    balanced_action TEXT NOT NULL CHECK (
        balanced_action IN ('BUY', 'SELL', 'HOLD', 'NO_TRADE')
    ),
    legacy_allocation_fraction REAL NOT NULL,
    shadow_allocation_fraction REAL NOT NULL,
    legacy_vix_multiplier REAL NOT NULL,
    shadow_vix_multiplier REAL NOT NULL,
    hard_gate_failures_json TEXT NOT NULL,
    order_authorized INTEGER NOT NULL DEFAULT 0 CHECK (order_authorized = 0),
    created_at_utc TEXT NOT NULL,
    UNIQUE (model_run_id, ticker, persona),
    FOREIGN KEY (model_run_id) REFERENCES model_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_prediction_audit_lookup
    ON stock_prediction_decision_audits (model_run_id, persona, ticker);

CREATE TABLE IF NOT EXISTS stock_prediction_criterion_audits (
    audit_id TEXT NOT NULL,
    criterion_ordinal INTEGER NOT NULL CHECK (criterion_ordinal >= 0),
    criterion TEXT NOT NULL,
    ag_rule TEXT NOT NULL,
    ag_result TEXT NOT NULL,
    codex_rule TEXT NOT NULL,
    codex_result TEXT NOT NULL,
    balanced_rule TEXT NOT NULL,
    balanced_result TEXT NOT NULL,
    PRIMARY KEY (audit_id, criterion_ordinal),
    FOREIGN KEY (audit_id) REFERENCES stock_prediction_decision_audits(audit_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_prediction_criterion_lookup
    ON stock_prediction_criterion_audits (audit_id, criterion_ordinal);
