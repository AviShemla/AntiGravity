-- Additive, review-only scorecard lineage guard.
-- This migration is intentionally unapplied until exact SQL review and Turso
-- staging verification are complete. It never mutates existing rows.
--
-- Current production boundary: only STOCK scorecards are admitted. ETF and
-- ARENA scorecards fail closed until their input-role policies are implemented.

CREATE TRIGGER IF NOT EXISTS trg_model_scorecards_lineage_insert
BEFORE INSERT ON model_scorecards
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM model_runs run
    WHERE run.run_id = NEW.run_id
      AND run.asset_class = 'STOCK'
      AND run.status = 'STARTED'
      AND run.source_session_date < run.prediction_date
      AND (
          SELECT COUNT(*)
          FROM model_run_inputs input
          WHERE input.run_id = run.run_id
      ) = 2
      AND EXISTS (
          SELECT 1
          FROM model_run_inputs input
          JOIN model_input_snapshots snapshot
            ON snapshot.snapshot_id = input.snapshot_id
          WHERE input.run_id = run.run_id
            AND input.input_role = 'MARKET_FEATURES'
            AND input.snapshot_checksum_sha256 = snapshot.source_checksum_sha256
            AND snapshot.dataset_type = 'MARKET_FEATURES'
            AND snapshot.status = 'VALIDATED'
            AND snapshot.source_session_date = run.source_session_date
            AND snapshot.available_at_utc <= run.as_of_timestamp_utc
      )
      AND EXISTS (
          SELECT 1
          FROM model_run_inputs input
          JOIN model_input_snapshots snapshot
            ON snapshot.snapshot_id = input.snapshot_id
          JOIN model_input_approval_events approval
            ON approval.snapshot_id = snapshot.snapshot_id
          WHERE input.run_id = run.run_id
            AND input.input_role = 'STOCK_UNIVERSE'
            AND input.snapshot_checksum_sha256 = snapshot.source_checksum_sha256
            AND snapshot.dataset_type = 'STOCK_UNIVERSE'
            AND snapshot.status = 'VALIDATED'
            AND snapshot.source_session_date = run.source_session_date
            AND snapshot.available_at_utc <= run.as_of_timestamp_utc
            AND approval.decision = 'APPROVED'
            AND approval.snapshot_checksum_sha256 = snapshot.source_checksum_sha256
            AND approval.decided_at_utc <= run.as_of_timestamp_utc
            AND approval.event_id = (
                SELECT latest.event_id
                FROM model_input_approval_events latest
                WHERE latest.snapshot_id = snapshot.snapshot_id
                  AND latest.decided_at_utc <= run.as_of_timestamp_utc
                ORDER BY latest.decided_at_utc DESC, latest.event_id DESC
                LIMIT 1
            )
      )
)
BEGIN
    SELECT RAISE(ABORT, 'model_scorecard_lineage_not_proven');
END;

CREATE TRIGGER IF NOT EXISTS trg_model_scorecards_lineage_update
BEFORE UPDATE ON model_scorecards
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'model_scorecards_are_immutable');
END;
