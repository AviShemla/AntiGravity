# Data-governance schema change plan — 2026-08-24

Mode: research/paper migration. This document is a change plan, not deployment
authority. Neither migration described here has been applied to Turso.

## Objective

Create append-only evidence structures for:

1. approved provider-selection policy and immutable canonical EOD bars;
2. exact affected feature-recomputation keys and output lineage; and
3. one AG-versus-Codex-versus-balanced audit for every stock prediction and
   persona, including every criterion row.

No existing table or row is altered. The migrations contain only
`CREATE TABLE IF NOT EXISTS` and `CREATE [UNIQUE] INDEX IF NOT EXISTS`.

## Reviewed artifacts

### Canonical market lineage

- File: `migrations/20260824_canonical_market_lineage_additive.sql`
- SHA-256:
  `db10c366a7ef6adfdf6dbe6f4c39fe1fe4b3a2e573f393ed099e3b3028df542a`
- Guarded parser result: 10 create-only statements, `no_changes=true`.
- Tables: canonical policies, canonical bar snapshots, canonical bars,
  feature recompute runs, and exact feature recompute keys.

### Stock prediction policy audit

- File: `migrations/20260824_stock_prediction_audit_additive.sql`
- SHA-256:
  `8ff5931429ceaba8713ec6d7f2efafa343292e0e4727b7835e782f31600d95c2`
- Guarded parser result: four create-only statements, `no_changes=true`.
- Tables: one decision audit per model-run/ticker/persona and its ordered
  criterion comparison rows.
- `order_authorized` is constrained to zero by schema.

## Preconditions

All conditions must be re-read immediately before deployment:

1. GitHub `origin/master` equals the cloud worktree HEAD and the worktree is
   clean.
2. Each migration's byte-level SHA-256 equals the reviewed value above.
3. Full protected test suite is green.
4. Staged/tracked secret scans report no high-confidence credential.
5. `ag-sniper.service`, `antigravity-nightly.timer`, and
   `antigravity-qa-watchdog.timer` are inactive and disabled.
6. No model, order, ledger, or ingestion writer is running concurrently.
7. The owner explicitly approves applying these exact hashes.

## Deployment

Use the guarded create-only migration tool with `--apply` and the exact
reviewed SHA-256. The tool rejects any non-create statement and refuses a hash
mismatch. Apply one artifact at a time; verify the first before applying the
second.

## Post-deployment verification

For each migration:

1. Read back exact table and index names from Turso metadata.
2. Read back every expected column, primary key, foreign key, uniqueness rule,
   status check, and the `order_authorized = 0` constraint.
3. Prove all newly created tables contain zero rows.
4. Re-run the protected repository suite.
5. Re-read the protected systemd unit states.
6. Record the migration SHA, application timestamp, Turso readback counts,
   Git commit, and test count in the recovery checkpoint.

Creating empty schema is not authorization to write canonical bars, feature
patches, model outputs, audits, recommendations, or orders. Each writer path
requires separate focused tests and explicit run approval.

## Failure and rollback behavior

The migration is idempotent and create-only. If connectivity fails after a
partial application, stop and inspect which empty objects exist. Do not drop
them automatically. After root cause and hash verification, safely re-run the
same migration; `IF NOT EXISTS` completes only missing objects.

If an incorrect schema is discovered, leave it unused, mark deployment failed,
and prepare a separately reviewed correction. Destructive `DROP` rollback is
not authorized by this plan.
