-- migration-id: 20260825_normalized_lag_edges_v2
-- schema-version: 2
-- review-state: REVIEW_ONLY
-- This additive migration is not approved for production application.
-- Chain depth (1..5) and per-edge lag horizon (1..7 sessions) are independent.
-- Statements use explicit markers so trigger bodies are never split on ";".

-- statement: 001_migration_ledger
CREATE TABLE IF NOT EXISTS schema_migration_events_v2 (
    event_id TEXT PRIMARY KEY,
    migration_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    operation TEXT NOT NULL CHECK (operation IN ('APPLY', 'ROLLBACK')),
    parent_event_id TEXT,
    actor TEXT NOT NULL,
    target_database_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    executed_at_utc TEXT NOT NULL CHECK (
        length(executed_at_utc) = 20
        AND executed_at_utc GLOB '????-??-??T??:??:??Z'
    ),
    UNIQUE (migration_id, operation, artifact_sha256),
    FOREIGN KEY (parent_event_id) REFERENCES schema_migration_events_v2(event_id)
)
-- end-statement

-- statement: 002_migration_ledger_no_update
CREATE TRIGGER IF NOT EXISTS trg_schema_migration_events_v2_no_update
BEFORE UPDATE ON schema_migration_events_v2
BEGIN
    SELECT RAISE(ABORT, 'schema migration events are append-only');
END
-- end-statement

-- statement: 003_migration_ledger_no_delete
CREATE TRIGGER IF NOT EXISTS trg_schema_migration_events_v2_no_delete
BEFORE DELETE ON schema_migration_events_v2
BEGIN
    SELECT RAISE(ABORT, 'schema migration events cannot be deleted');
END
-- end-statement

-- statement: 004_screening_edge_sets
CREATE TABLE IF NOT EXISTS predictive_screening_edge_sets_v2 (
    screening_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL CHECK (trim(ticker) <> '' AND ticker = upper(ticker)),
    declared_depth INTEGER NOT NULL CHECK (declared_depth BETWEEN 1 AND 5),
    lag_semantics TEXT NOT NULL CHECK (
        lag_semantics = 'TARGET_RELATIVE_TRADING_SESSIONS'
    ),
    edge_spec_sha256 TEXT NOT NULL CHECK (length(edge_spec_sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'FROZEN')),
    created_at_utc TEXT NOT NULL CHECK (
        length(created_at_utc) = 20
        AND created_at_utc GLOB '????-??-??T??:??:??Z'
    ),
    frozen_at_utc TEXT CHECK (
        frozen_at_utc IS NULL OR (
            length(frozen_at_utc) = 20
            AND frozen_at_utc GLOB '????-??-??T??:??:??Z'
        )
    ),
    PRIMARY KEY (screening_run_id, ticker),
    FOREIGN KEY (screening_run_id, ticker)
        REFERENCES predictive_screening_results(screening_run_id, ticker)
)
-- end-statement

-- statement: 005_screening_edges
CREATE TABLE IF NOT EXISTS predictive_screening_edges_v2 (
    screening_run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    edge_position INTEGER NOT NULL CHECK (edge_position BETWEEN 1 AND 5),
    predictor_ticker TEXT NOT NULL CHECK (
        trim(predictor_ticker) <> '' AND predictor_ticker = upper(predictor_ticker)
    ),
    lag_sessions INTEGER NOT NULL CHECK (lag_sessions BETWEEN 1 AND 7),
    lag_semantics TEXT NOT NULL CHECK (
        lag_semantics = 'TARGET_RELATIVE_TRADING_SESSIONS'
    ),
    created_at_utc TEXT NOT NULL CHECK (
        length(created_at_utc) = 20
        AND created_at_utc GLOB '????-??-??T??:??:??Z'
    ),
    PRIMARY KEY (screening_run_id, ticker, edge_position),
    UNIQUE (screening_run_id, ticker, predictor_ticker, lag_sessions),
    FOREIGN KEY (screening_run_id, ticker)
        REFERENCES predictive_screening_edge_sets_v2(screening_run_id, ticker)
)
-- end-statement

-- statement: 006_screening_edge_insert_guard
CREATE TRIGGER IF NOT EXISTS trg_predictive_screening_edges_v2_insert_guard
BEFORE INSERT ON predictive_screening_edges_v2
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM predictive_screening_edge_sets_v2 s
        WHERE s.screening_run_id = NEW.screening_run_id
          AND s.ticker = NEW.ticker
          AND s.status = 'DRAFT'
          AND s.lag_semantics = NEW.lag_semantics
          AND NEW.edge_position <= s.declared_depth
    ) THEN RAISE(ABORT, 'screening edge requires matching DRAFT edge set') END;
END
-- end-statement

-- statement: 007_screening_edge_no_update
CREATE TRIGGER IF NOT EXISTS trg_predictive_screening_edges_v2_no_update
BEFORE UPDATE ON predictive_screening_edges_v2
BEGIN
    SELECT RAISE(ABORT, 'screening edges are immutable');
END
-- end-statement

-- statement: 008_screening_edge_no_delete
CREATE TRIGGER IF NOT EXISTS trg_predictive_screening_edges_v2_no_delete
BEFORE DELETE ON predictive_screening_edges_v2
BEGIN
    SELECT RAISE(ABORT, 'screening edges cannot be deleted');
END
-- end-statement

-- statement: 009_screening_set_freeze_guard
CREATE TRIGGER IF NOT EXISTS trg_predictive_screening_edge_sets_v2_freeze
BEFORE UPDATE ON predictive_screening_edge_sets_v2
BEGIN
    SELECT CASE WHEN
        OLD.status <> 'DRAFT' OR NEW.status <> 'FROZEN'
        OR NEW.screening_run_id <> OLD.screening_run_id
        OR NEW.ticker <> OLD.ticker
        OR NEW.declared_depth <> OLD.declared_depth
        OR NEW.lag_semantics <> OLD.lag_semantics
        OR NEW.edge_spec_sha256 <> OLD.edge_spec_sha256
        OR NEW.created_at_utc <> OLD.created_at_utc
        OR NEW.frozen_at_utc IS NULL
    THEN RAISE(ABORT, 'screening edge set permits only DRAFT to FROZEN') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM predictive_screening_edges_v2 e
        WHERE e.screening_run_id = OLD.screening_run_id AND e.ticker = OLD.ticker
    ) <> OLD.declared_depth
    THEN RAISE(ABORT, 'screening edge count must equal declared depth') END;
    SELECT CASE WHEN (
        SELECT COALESCE(MIN(edge_position), 0) FROM predictive_screening_edges_v2 e
        WHERE e.screening_run_id = OLD.screening_run_id AND e.ticker = OLD.ticker
    ) <> 1 OR (
        SELECT COALESCE(MAX(edge_position), 0) FROM predictive_screening_edges_v2 e
        WHERE e.screening_run_id = OLD.screening_run_id AND e.ticker = OLD.ticker
    ) <> OLD.declared_depth
    THEN RAISE(ABORT, 'screening edge positions must be dense') END;
END
-- end-statement

-- statement: 010_screening_set_no_delete
CREATE TRIGGER IF NOT EXISTS trg_predictive_screening_edge_sets_v2_no_delete
BEFORE DELETE ON predictive_screening_edge_sets_v2
BEGIN
    SELECT RAISE(ABORT, 'screening edge sets cannot be deleted');
END
-- end-statement

-- statement: 011_universe_edge_sets
CREATE TABLE IF NOT EXISTS stock_universe_edge_sets_v2 (
    universe_snapshot_id TEXT NOT NULL,
    target_ticker TEXT NOT NULL CHECK (
        trim(target_ticker) <> '' AND target_ticker = upper(target_ticker)
    ),
    source_screening_run_id TEXT NOT NULL,
    source_screening_ticker TEXT NOT NULL,
    declared_depth INTEGER NOT NULL CHECK (declared_depth BETWEEN 1 AND 5),
    lag_semantics TEXT NOT NULL CHECK (
        lag_semantics = 'TARGET_RELATIVE_TRADING_SESSIONS'
    ),
    edge_spec_sha256 TEXT NOT NULL CHECK (length(edge_spec_sha256) = 64),
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'FROZEN')),
    created_at_utc TEXT NOT NULL CHECK (
        length(created_at_utc) = 20
        AND created_at_utc GLOB '????-??-??T??:??:??Z'
    ),
    frozen_at_utc TEXT CHECK (
        frozen_at_utc IS NULL OR (
            length(frozen_at_utc) = 20
            AND frozen_at_utc GLOB '????-??-??T??:??:??Z'
        )
    ),
    PRIMARY KEY (universe_snapshot_id, target_ticker),
    FOREIGN KEY (universe_snapshot_id, target_ticker)
        REFERENCES stock_universe_config(snapshot_id, ticker),
    FOREIGN KEY (source_screening_run_id, source_screening_ticker)
        REFERENCES predictive_screening_edge_sets_v2(screening_run_id, ticker)
)
-- end-statement

-- statement: 012_universe_edges
CREATE TABLE IF NOT EXISTS stock_universe_edges_v2 (
    universe_snapshot_id TEXT NOT NULL,
    target_ticker TEXT NOT NULL,
    edge_position INTEGER NOT NULL CHECK (edge_position BETWEEN 1 AND 5),
    predictor_ticker TEXT NOT NULL CHECK (
        trim(predictor_ticker) <> '' AND predictor_ticker = upper(predictor_ticker)
    ),
    lag_sessions INTEGER NOT NULL CHECK (lag_sessions BETWEEN 1 AND 7),
    lag_semantics TEXT NOT NULL CHECK (
        lag_semantics = 'TARGET_RELATIVE_TRADING_SESSIONS'
    ),
    created_at_utc TEXT NOT NULL CHECK (
        length(created_at_utc) = 20
        AND created_at_utc GLOB '????-??-??T??:??:??Z'
    ),
    PRIMARY KEY (universe_snapshot_id, target_ticker, edge_position),
    UNIQUE (universe_snapshot_id, target_ticker, predictor_ticker, lag_sessions),
    FOREIGN KEY (universe_snapshot_id, target_ticker)
        REFERENCES stock_universe_edge_sets_v2(universe_snapshot_id, target_ticker)
)
-- end-statement

-- statement: 013_universe_edge_insert_guard
CREATE TRIGGER IF NOT EXISTS trg_stock_universe_edges_v2_insert_guard
BEFORE INSERT ON stock_universe_edges_v2
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM stock_universe_edge_sets_v2 s
        WHERE s.universe_snapshot_id = NEW.universe_snapshot_id
          AND s.target_ticker = NEW.target_ticker
          AND s.status = 'DRAFT'
          AND s.lag_semantics = NEW.lag_semantics
          AND NEW.edge_position <= s.declared_depth
    ) THEN RAISE(ABORT, 'universe edge requires matching DRAFT edge set') END;
END
-- end-statement

-- statement: 014_universe_edge_no_update
CREATE TRIGGER IF NOT EXISTS trg_stock_universe_edges_v2_no_update
BEFORE UPDATE ON stock_universe_edges_v2
BEGIN
    SELECT RAISE(ABORT, 'universe edges are immutable');
END
-- end-statement

-- statement: 015_universe_edge_no_delete
CREATE TRIGGER IF NOT EXISTS trg_stock_universe_edges_v2_no_delete
BEFORE DELETE ON stock_universe_edges_v2
BEGIN
    SELECT RAISE(ABORT, 'universe edges cannot be deleted');
END
-- end-statement

-- statement: 016_universe_set_freeze_guard
CREATE TRIGGER IF NOT EXISTS trg_stock_universe_edge_sets_v2_freeze
BEFORE UPDATE ON stock_universe_edge_sets_v2
BEGIN
    SELECT CASE WHEN
        OLD.status <> 'DRAFT' OR NEW.status <> 'FROZEN'
        OR NEW.universe_snapshot_id <> OLD.universe_snapshot_id
        OR NEW.target_ticker <> OLD.target_ticker
        OR NEW.source_screening_run_id <> OLD.source_screening_run_id
        OR NEW.source_screening_ticker <> OLD.source_screening_ticker
        OR NEW.declared_depth <> OLD.declared_depth
        OR NEW.lag_semantics <> OLD.lag_semantics
        OR NEW.edge_spec_sha256 <> OLD.edge_spec_sha256
        OR NEW.created_at_utc <> OLD.created_at_utc
        OR NEW.frozen_at_utc IS NULL
    THEN RAISE(ABORT, 'universe edge set permits only DRAFT to FROZEN') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM predictive_screening_edge_sets_v2 s
        WHERE s.screening_run_id = OLD.source_screening_run_id
          AND s.ticker = OLD.source_screening_ticker
          AND s.status = 'FROZEN'
          AND s.declared_depth = OLD.declared_depth
          AND s.lag_semantics = OLD.lag_semantics
          AND s.edge_spec_sha256 = OLD.edge_spec_sha256
    ) THEN RAISE(ABORT, 'universe edge set requires matching frozen screening evidence') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM stock_universe_edges_v2 e
        WHERE e.universe_snapshot_id = OLD.universe_snapshot_id
          AND e.target_ticker = OLD.target_ticker
    ) <> OLD.declared_depth
    THEN RAISE(ABORT, 'universe edge count must equal declared depth') END;
    SELECT CASE WHEN EXISTS (
        SELECT edge_position, predictor_ticker, lag_sessions, lag_semantics
        FROM predictive_screening_edges_v2
        WHERE screening_run_id = OLD.source_screening_run_id
          AND ticker = OLD.source_screening_ticker
        EXCEPT
        SELECT edge_position, predictor_ticker, lag_sessions, lag_semantics
        FROM stock_universe_edges_v2
        WHERE universe_snapshot_id = OLD.universe_snapshot_id
          AND target_ticker = OLD.target_ticker
    ) OR EXISTS (
        SELECT edge_position, predictor_ticker, lag_sessions, lag_semantics
        FROM stock_universe_edges_v2
        WHERE universe_snapshot_id = OLD.universe_snapshot_id
          AND target_ticker = OLD.target_ticker
        EXCEPT
        SELECT edge_position, predictor_ticker, lag_sessions, lag_semantics
        FROM predictive_screening_edges_v2
        WHERE screening_run_id = OLD.source_screening_run_id
          AND ticker = OLD.source_screening_ticker
    ) THEN RAISE(ABORT, 'universe edges must exactly equal screening edges') END;
END
-- end-statement

-- statement: 017_universe_set_no_delete
CREATE TRIGGER IF NOT EXISTS trg_stock_universe_edge_sets_v2_no_delete
BEFORE DELETE ON stock_universe_edge_sets_v2
BEGIN
    SELECT RAISE(ABORT, 'universe edge sets cannot be deleted');
END
-- end-statement

-- statement: 018_screening_lookup_index
CREATE INDEX IF NOT EXISTS idx_predictive_screening_edges_v2_lookup
ON predictive_screening_edges_v2
   (screening_run_id, ticker, edge_position, predictor_ticker, lag_sessions)
-- end-statement

-- statement: 019_universe_lookup_index
CREATE INDEX IF NOT EXISTS idx_stock_universe_edges_v2_lookup
ON stock_universe_edges_v2
   (universe_snapshot_id, target_ticker, edge_position, predictor_ticker, lag_sessions)
-- end-statement
