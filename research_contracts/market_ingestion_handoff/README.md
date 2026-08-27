# Guarded ingestion postflight and single-owner handoff

This package implements the S01 repair without contacting production or
writing to Turso.

- `market_ingestion_postflight.py` performs pure exact-set reconciliation for
  474 feature tickers plus required macro lineage `^TNX` and `^VIX`.
- `market_ingestion_postflight_cli.py` permits only six SELECT statements,
  normalizes the Turso endpoint to `/v2/pipeline`, retries only incomplete
  visibility for a bounded number of attempts, and writes a local mode-0600
  create-once handoff artifact.
- `audit_handoff_topology.py` rejects a missing or duplicate `OnSuccess` owner.
- `verify_postflight_handoff.py` independently verifies canonical JSON, the
  embedded evidence hash, STAGING lifecycle, zero downstream outputs, count
  reconciliation, source session, freshness, and root/0600 file properties on
  POSIX before the baseline successor can start.
- `systemd/` defines the single chain ingestion -> postflight -> handoff ->
  baseline. Only `codex-market-ingestion-handoff@.service` owns the baseline
  `OnSuccess` transition.

The templates are design artifacts, not deployed units. Their credential file
reference names a future root-owned read-only environment file; no credential
is stored here.
