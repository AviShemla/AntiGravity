-- Append-only evidence for owner-approved quarantine fresh starts.
-- This table never deletes or rewrites ledger, scorecard, or run history.

CREATE TABLE IF NOT EXISTS quarantine_reset_events (
    reset_id TEXT PRIMARY KEY,
    asset_class TEXT NOT NULL CHECK (asset_class IN ('STOCK', 'ETF')),
    mechanism TEXT NOT NULL CHECK (
        mechanism IN ('LEGACY_STRIKE_BLACKLIST', 'MODEL_FAILURE')
    ),
    effective_session_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(asset_class, mechanism, effective_session_date)
);

CREATE INDEX IF NOT EXISTS idx_quarantine_reset_effective
    ON quarantine_reset_events(asset_class, mechanism, effective_session_date);
