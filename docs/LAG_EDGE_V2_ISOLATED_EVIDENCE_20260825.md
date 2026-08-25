# Isolated lag-edge v2 behavioral evidence  2026-08-25

Status: COMPLETE on a disposable, non-production Turso branch. No production
schema application, model run, recommendation, order, promotion, or trading
activation occurred.

## Identity and pre-state

- Production database: `theoracle`
- Production database id: `019f09f6-0701-72e9-aad2-c64996ae63e1`
- Disposable branch: `theoracle-codex-lagv2-20260825t1022z`
- Disposable branch id: `01a0386f-2e01-7373-bdb0-f47e29c97ced`
- Parent: `theoracle`
- Region: `aws-eu-west-1`
- Initial branch schema objects: 63
- Initial branch v2 objects: 0
- Initial branch/production pre-state fingerprint:
  `50e2bf55c3835c1d7d15e87b1bf2038e5e8b38f395a408fef10fc37e4df9f11f`

## Migration identity

- Artifact: `migrations/20260825_normalized_lag_edges_v2.sql`
- Artifact SHA-256:
  `9dd4e1c227238c4a354ed2e9d4683ac7e042c535222ed3ab6ef124abe2545bdb`
- Apply event: `evt-lagv2-apply-20260825t1025z`
- Target database id: `01a0386f-2e01-7373-bdb0-f47e29c97ced`
- Parsed statements: 19

## Behavioral matrix

The isolated branch produced 55 direct PASS assertions covering:

- valid chain depths 1 and 5;
- independent, non-monotonic per-edge lags including 7, 5, 2, 6, 1;
- rejection of depths 0 and 6;
- rejection of lags 0 and 8;
- dense-edge and source-freeze prerequisites;
- exactly equal source/universe edge sets permitting the only freeze;
- a missing or differing edge blocking freeze;
- immutable frozen headers and edges;
- DELETE protection for sets, edges, and migration ledger;
- immutable ledger actor;
- versioned universe snapshots;
- approval, revocation, latest-snapshot, and latest-approval selection.

A deliberate failing migration executed through the repaired baton runner raised
`AtomicMigrationError`, left the probe table count at zero, never sent
`COMMIT`, and verified `ROLLBACK`.

## Logical rollback readback

- Rollback event: `evt-lagv2-rollback-20260825t1045z`
- Parent event: `evt-lagv2-apply-20260825t1025z`
- Latest ledger operation: `ROLLBACK`
- Ledger event count: 2
- V2 objects retained for forensic evidence: 27
- Frozen screening sets retained: 2
- Branch schema objects after matrix: 82
- Branch post-state fingerprint:
  `147ec978ccb623ce924e51f08bcf5109f920d0ea29301df29c7a839391442eb2`

The rollback is intentionally logical and non-destructive; v2 schema and
append-only evidence remain on the disposable branch until resource cleanup.


## Production post-test readback

A read-only post-test query returned:

- schema objects: 63 (same as the recorded pre-state);
- v2 objects: 0 (same as the recorded pre-state);
- canonical post-readback fingerprint using JSON row serialization:
  `31c3088ca005bb426423990cff031574d3153ded908c83516ff756cf4c201895`.

The post fingerprint uses a newly documented serialization and therefore is not
presented as directly comparable to the older pre-state fingerprint above.
The stable object count and absence of every v2 object independently prove that
this migration was not applied to production.

## Repository verification

- Focused migration/schema suite: 21 passed.
- Full repository suite: 338 passed, 11 subtests passed, 2 failed.
- Both failures are legacy `tests/test_ledgers.py` integration tests. With no
  credentials they fail closed before SQL; with a newly minted one-day
  read-only production token they still fail at the legacy Hrana WebSocket
  handshake with HTTP 400. They do not exercise the v2 migration path.
