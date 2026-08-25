# Lag-edge v2 production application evidence - 2026-08-25

Status: COMMITTED AND READBACK-GREEN

Owner approval scope: apply the normalized lag-edge v2 schema to production
only, conditional on a reliable crisis recovery branch. No model, snapshot
validation/promotion, recommendation, order, email, service activation, or
trading action was authorized or performed.

## Git and artifact identity

- Git/GitHub HEAD at application:
  `74ec66a53da3a8d9353156ed161d894f171d6d3e`
- Worktree state: clean.
- Migration: `migrations/20260825_normalized_lag_edges_v2.sql`
- Exact SHA-256:
  `9dd4e1c227238c4a354ed2e9d4683ac7e042c535222ed3ab6ef124abe2545bdb`
- Check-only parse: 19 statements, no changes.
- Production database id:
  `019f09f6-0701-72e9-aad2-c64996ae63e1`

## Frozen-writer and timer evidence

Before application:

- `ag-sniper.service`: inactive, disabled;
- `antigravity-nightly.service`: not running, disabled;
- `antigravity-qa-watchdog.service`: not running, disabled;
- `codex-market-ingestion-20260825-v1.service`: inactive;
- all searched model/order/backtest/screening processes: absent;
- `ag-vix.service` was found active and was stopped before application.

The guarded ingestion timer was not disturbed:

- `codex-market-ingestion-20260825-v1.timer`: active, enabled, waiting;
- next trigger: `2026-08-26 00:30:00 UTC`.

At final readback `ag-vix.service` remained inactive. It remains enabled, but
was not reactivated as part of this schema operation.

## Canonical production pre-state

- explicit schema objects: 63;
- v2 explicit objects: 0;
- legacy tables: 36;
- total legacy rows: 2,844,645;
- schema fingerprint:
  `31c3088ca005bb426423990cff031574d3153ded908c83516ff756cf4c201895`;
- legacy per-table row-count fingerprint:
  `e7d001fb7591636f72709b33eb8ebfc70cfe8ed3a7c02e13ef4e2f079981affb`;
- legacy boundary-anchor fingerprint:
  `b670c663b409f4986d9158eb8ebdc1b86163fa612b26afd835ff56c2e97746a1`;
- `predictive_screening_results`: 1,493 rows, fingerprint
  `2301d2be200e81e992a6b022a79d475d00fc074d1e92360ce169401f29e84f91`;
- `stock_universe_config`: 0 rows, fingerprint
  `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.

## Retained crisis recovery branch

A point-in-time Turso branch was created from production at the captured
pre-state and is intentionally retained:

- name: `theoracle-recovery-prelagv2-20260825t1225z`;
- id: `01a038e0-7201-7d7e-9e93-4c7c960c7f3f`;
- parent: `theoracle`;
- region: `aws-eu-west-1`;
- materialized size: 1.4 GB;
- delete protection: enabled.

The branch is queryable and matched production pre-state exactly on:

- explicit schema count 63 and schema fingerprint
  `31c3088ca005bb426423990cff031574d3153ded908c83516ff756cf4c201895`;
- 36 legacy table boundary-anchor fingerprint
  `b670c663b409f4986d9158eb8ebdc1b86163fa612b26afd835ff56c2e97746a1`;
- both parent-table row counts and full data fingerprints;
- zero v2 objects.

Do not delete, modify, or repurpose this branch without separate owner
approval. A broad restore is not automatic.

## Application event and protocol observation

The production transaction wrote this append-only event:

- event id: `evt-lagv2-prod-20260825t12331787661208z`;
- migration id: `20260825_normalized_lag_edges_v2`;
- schema version: 2;
- operation: `APPLY`;
- actor: `codexops-production-migration`;
- target database id:
  `019f09f6-0701-72e9-aad2-c64996ae63e1`;
- executed at: `2026-08-25T12:33:29Z`;
- artifact SHA-256: the exact pinned hash above.

The first CLI result was a false negative:
`Migration failed and rollback could not be verified: HTTP 404`.
No retry or broad restore was attempted.

Independent readback proved that COMMIT had already succeeded. A protocol probe
then proved Turso behavior:

1. BEGIN returns HTTP 200, an `ok` result, and a baton;
2. a statement under the baton returns HTTP 200, `ok`, and a baton;
3. COMMIT returns HTTP 200 and `ok`, but no baton;
4. therefore a post-COMMIT baton close is invalid and must not be required.

The runner was repaired so a proven terminal COMMIT or ROLLBACK does not require
a baton or close request. Any uncertain COMMIT response still remains a crisis
state requiring independent readback.

## Mandatory post-application readback

All schema and data invariants passed:

- explicit schema objects: exactly 82 (63 + 19);
- explicit v2 objects: exactly 19;
- expected object types: 5 tables, 12 triggers, 2 indexes;
- production v2 schema fingerprint:
  `e7c2bd24656fe4909df3fa232650e115552d4c1e4aedb718540663e42cf9e884`;
- independently constructed expected v2 fingerprint:
  `e7c2bd24656fe4909df3fa232650e115552d4c1e4aedb718540663e42cf9e884`;
- ledger: exactly one matching APPLY event;
- screening edge sets/edges: 0/0 rows;
- universe edge sets/edges: 0/0 rows;
- foreign-key enforcement: enabled;
- no ROLLBACK event supersedes the APPLY event.

Unrelated production data was unchanged:

- legacy tables: 36;
- total legacy rows: 2,844,645;
- legacy row-count fingerprint: unchanged
  `e7d001fb7591636f72709b33eb8ebfc70cfe8ed3a7c02e13ef4e2f079981affb`;
- legacy boundary-anchor fingerprint: unchanged
  `b670c663b409f4986d9158eb8ebdc1b86163fa612b26afd835ff56c2e97746a1`;
- both parent-table counts and full data fingerprints: unchanged.

## Crisis rollback rule

The retained recovery branch is the point-in-time crisis asset. Because current
post-COMMIT invariants are green, no restore is warranted.

If a later critical defect is proven:

1. freeze all writers and preserve current production evidence;
2. do not delete or overwrite production automatically;
3. obtain separate owner approval for the exact recovery action;
4. prefer a reviewed logical ROLLBACK event when readers can fail closed;
5. use the retained branch for forensic comparison or a separately approved
   recovery plan;
6. independently verify every schema/data invariant after recovery.
