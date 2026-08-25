# Lag-edge v2 production schema approval package

Status: APPROVED AND APPLIED ON 2026-08-25; see `LAG_EDGE_V2_PRODUCTION_APPLICATION_EVIDENCE_20260825.md`.

Prepared from GitHub master `5be1e38e7c2dacb5935b2a05945a0b7072167f06`.
Read-only production preflight timestamp: `2026-08-25T11:42:46Z`.

This document provides evidence for a separate owner approval decision. It
does not authorize a production schema write, model run, recommendation, order,
service activation, snapshot validation/promotion, or trading.

## Pinned artifact

- Migration: `migrations/20260825_normalized_lag_edges_v2.sql`
- Migration id: `20260825_normalized_lag_edges_v2`
- Schema version: 2
- Exact SHA-256:
  `9dd4e1c227238c4a354ed2e9d4683ac7e042c535222ed3ab6ef124abe2545bdb`
- Parsed statement count: 19
- Explicit object delta: 19 objects:
  - 5 tables;
  - 12 triggers;
  - 2 indexes.
- Production explicit-object count before application: 63.
- Expected production explicit-object count after successful application: 82.

The count excludes SQLite internal objects whose names begin with
`sqlite_`. The artifact must not be edited after approval. Any byte change
requires a new hash, a new isolated test branch, and renewed approval.

## Production target and read-only compatibility preflight

Target identity read back from the Turso control plane:

- database name: `theoracle`;
- database id: `019f09f6-0701-72e9-aad2-c64996ae63e1`;
- group: `default`;
- location: `aws-eu-west-1`;
- reported size: 1.4 GB;
- SQLite version: 3.47.0.

Read-only SQL preflight returned:

- explicit schema objects: 63;
- objects with v2 names: 0;
- collisions with all 19 proposed explicit object names: 0;
- required parent tables present: 2 of 2;
- foreign-key enforcement: enabled.

Required parent-key compatibility was read directly from production:

- `predictive_screening_results` has primary key
  `(screening_run_id, ticker)`;
- `stock_universe_config` has primary key
  `(snapshot_id, ticker)`.

These keys satisfy the two composite foreign keys introduced by the migration.
Canonical production parent-table SQL hashes at preflight were:

- `predictive_screening_results`:
  `4b10b0ad92b78634e38a2d0137174dfe76a7d818767ae991ddd80331b310e5d1`;
- `stock_universe_config`:
  `3025ea5cde6b894f2287457437fa20993bdde859b9e47df517af8ee36cd5aa72`.

The existing positional lag columns remain untouched.

At the same preflight, these safety units were inactive and disabled:

- `ag-sniper.service`;
- `antigravity-nightly.timer`;
- `antigravity-qa-watchdog.timer`.

## Isolated evidence already completed

Disposable Turso branch
`theoracle-codex-lagv2-20260825t1022z` was derived from `theoracle`,
tested, logically rolled back, and destroyed after evidence preservation.

Verified evidence:

- 55 direct behavioral assertions passed;
- valid chain depth is 1 through 5;
- each edge independently accepts lag 1 through 7;
- non-monotonic lags such as 7, 5, 2, 6, 1 passed;
- invalid depths and lags were rejected;
- dense-edge, freeze, exact-equality, immutability, and DELETE guards passed;
- a deliberate migration failure rolled back and left zero probe tables;
- focused migration suite: 21 passed;
- production remained at 63 explicit objects and 0 v2 objects.

Implementation evidence commit:
`3785c61f32cd636fdc93407a448de0cb4b741272`.

Cleanup evidence commit:
`203f50cd685d2a6991bc1e5e9a8807115efcc95e`.

## Failure-atomic method

The approved runner is `scripts/apply_atomic_migration.py`. Check-only is its
default. Application is failure-atomic through the Turso transaction baton:

1. send `BEGIN IMMEDIATE` and require a baton;
2. under that baton, send all 19 hash-pinned statements and the append-only
   APPLY ledger event, without a COMMIT request;
3. require every result to be `ok`;
4. send COMMIT only after all schema statements and the ledger passed;
5. require COMMIT success; a successful terminal COMMIT normally returns no
   baton and must not be followed by close or rollback;
6. on any failure before a proven COMMIT, send ROLLBACK and require its
   successful terminal response without requiring a returned baton.

An unconditional COMMIT is never placed in the same request as statements that
may fail.

## Ordered application procedure after separate owner approval

All placeholders below must be resolved and recorded before any write.

1. Freeze writers and re-read service/timer state.
2. Re-read Git HEAD and require the approved commit or a proven descendant.
3. Recompute the artifact SHA-256 and require the pinned value above.
4. Re-run check-only parsing; require 19 statements and `no_changes=true`.
5. Re-read Turso name, URL, and database id; require the exact production
   identity above.
6. Re-run the collision, parent-table, parent-key, foreign-key, object-count,
   and v2-object preflight queries.
7. Create a unique APPLY event id and canonical UTC-second timestamp.
8. Record the explicit owner approval id, operator identity, Git commit,
   artifact hash, production database id, and preflight evidence.
9. Invoke the runner once with `--apply`, the exact expected hash,
   `--target-environment production`, the explicit approval id, event id,
   actor, production database id, and evidence JSON.
10. Do not retry automatically. Classify any uncertain response as NO-GO until
    ledger and schema readback prove the outcome.
11. Run all readback assertions below before enabling any v2 writer.

The exact apply command must be constructed only in the approved maintenance
session so approval identifiers and evidence are current. Credentials must
remain in secret management and must never appear in shell history, logs, Git,
or this document.

## Mandatory post-application readback

A successful process exit is insufficient. Require all of the following:

1. explicit schema object count is exactly 82;
2. each of the 19 expected names exists once with its expected object type;
3. the five new tables contain zero rows immediately after schema application,
   except the migration ledger;
4. the migration ledger contains exactly one matching APPLY event with:
   - migration id `20260825_normalized_lag_edges_v2`;
   - schema version 2;
   - the pinned artifact SHA-256;
   - the exact production database id;
   - canonical UTC time;
   - recorded approval and Git evidence;
5. no ROLLBACK event supersedes that APPLY event;
6. foreign-key enforcement remains enabled;
7. legacy parent-table schemas and their preflight fingerprints are unchanged;
8. the three trading/nightly/watchdog units remain inactive and disabled;
9. the focused migration suite still passes;
10. no v2 model writer, recommendation generator, order creator, or trading
    service is started by this schema change.

Any failed or UNKNOWN assertion is NO-GO.

## Rollback plan

### Failure before COMMIT

The runner must perform transaction ROLLBACK and prove:

- explicit schema object count returned to 63;
- all 19 proposed object names are absent;
- no APPLY ledger event exists;
- legacy parent schemas are unchanged.

Do not retry automatically.

### Failure discovered after a proven COMMIT

Rollback is logical and non-destructive:

1. keep all writers frozen;
2. append one ROLLBACK event referencing the APPLY event, using a separately
   reviewed and approved operation;
3. make future v2 readers fail closed when the latest event is ROLLBACK;
4. verify legacy readers remain unchanged;
5. retain v2 schema and append-only events as forensic evidence.

Do not DROP tables, DELETE ledger events, rewrite immutable edges, or silently
reapply. A schema correction requires a new hash-pinned migration version and a
new isolated behavioral test.

## Downtime and operational expectation

The artifact is additive and creates empty tables, triggers, and indexes. It
does not rewrite the 1.4 GB production data set. The isolated branch completed
without an observed application outage, but no precise production lock duration
has been measured. Therefore:

- exact production downtime: UNKNOWN;
- expected dashboard impact: none, provided it remains read-only;
- expected database impact: a brief `BEGIN IMMEDIATE` write lock;
- approved maintenance window recommendation: five minutes with all writers
  frozen and no automatic retry;
- abort criterion: any lock, HTTP, baton, identity, hash, ledger, or readback
  uncertainty.

## Explicit GO/NO-GO checklist

GO requires every item to be true immediately before application:

- [ ] Avi provides explicit approval for this exact artifact hash and target id.
- [ ] A unique production approval id and APPLY event id are recorded.
- [ ] Git HEAD is clean and the approved commits are ancestors.
- [ ] SHA-256 equals the pinned value.
- [ ] Check-only parse returns exactly 19 statements.
- [ ] Turso target identity equals `019f09f6-0701-72e9-aad2-c64996ae63e1`.
- [ ] Production object count is 63 and proposed-name collision count is 0.
- [ ] Both parent tables and composite parent keys still match.
- [ ] Foreign-key enforcement is enabled.
- [ ] Focused tests pass and secret scan has zero hits.
- [ ] All model/order/trading writers are stopped.
- [ ] The three named safety units are inactive and disabled.
- [ ] A five-minute monitored maintenance window is open.
- [ ] Post-apply readback operator is present and ready.
- [ ] Automatic retry is disabled.

NO-GO if any item is false, stale, or UNKNOWN.
