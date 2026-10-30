-- Additive, review-only Turso migration for execution authorization.
-- Do not apply until reader/preflight tests and an approval workflow are reviewed.
-- Existing pending orders, ledgers, trades, and services are not modified.

CREATE TABLE IF NOT EXISTS execution_plans (
    plan_id TEXT PRIMARY KEY,
    persona TEXT NOT NULL,
    asset_class TEXT NOT NULL CHECK (asset_class IN ('STOCK', 'ETF')),
    target_date TEXT NOT NULL,
    source_session_date TEXT NOT NULL,
    market_snapshot_id TEXT NOT NULL,
    model_run_id TEXT NOT NULL,
    pending_payload_sha256 TEXT NOT NULL,
    qa_status TEXT NOT NULL CHECK (qa_status IN ('VALIDATED', 'REJECTED')),
    qa_evidence_json TEXT NOT NULL,
    code_version TEXT NOT NULL,
    config_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE (persona, target_date),
    FOREIGN KEY (market_snapshot_id) REFERENCES model_input_snapshots(snapshot_id),
    FOREIGN KEY (model_run_id) REFERENCES model_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_execution_plans_target
    ON execution_plans (target_date, persona, qa_status);

CREATE TABLE IF NOT EXISTS execution_events (
    event_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    persona TEXT NOT NULL,
    target_date TEXT NOT NULL,
    ticker TEXT,
    action TEXT NOT NULL CHECK (action IN (
        'BUY', 'SELL', 'HOLD', 'ABORT_BUY', 'ABORT_SELL',
        'TAKE_PROFIT', 'STOP_LOSS', 'KILL_SWITCH'
    )),
    units REAL,
    reference_price REAL,
    execution_price REAL,
    fees REAL NOT NULL DEFAULT 0 CHECK (fees >= 0),
    cash_delta REAL NOT NULL,
    holdings_value_delta REAL NOT NULL,
    realized_pnl REAL,
    reference_quote_timestamp_utc TEXT,
    before_state_sha256 TEXT NOT NULL,
    after_state_sha256 TEXT NOT NULL,
    previous_event_sha256 TEXT,
    event_sha256 TEXT NOT NULL UNIQUE,
    decision_evidence_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE (plan_id, sequence_number),
    FOREIGN KEY (plan_id) REFERENCES execution_plans(plan_id)
);

CREATE INDEX IF NOT EXISTS idx_execution_events_plan
    ON execution_events (plan_id, sequence_number);

CREATE TABLE IF NOT EXISTS execution_plan_approvals (
    plan_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    approved_by TEXT NOT NULL,
    approved_at_utc TEXT NOT NULL,
    approval_evidence TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES execution_plans(plan_id)
);

CREATE TABLE IF NOT EXISTS execution_plan_consumptions (
    consumption_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL UNIQUE,
    consumed_at_utc TEXT NOT NULL,
    execution_service TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('CONSUMED', 'ABORTED', 'FAILED')),
    evidence_json TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES execution_plans(plan_id)
);
