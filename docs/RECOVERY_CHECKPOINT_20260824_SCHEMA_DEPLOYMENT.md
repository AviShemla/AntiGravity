# Recovery checkpoint — governed schema deployment — 2026-08-24

Mode: research/paper migration.

Verified at 2026-08-24T19:24:51Z (22:24 Israel time).

## Git source

- Pre-deployment GitHub/Vultr HEAD:
  `253323e69a0dbc52eeefbfc21e50230c5c8df958`.
- The Vultr cloud worktree was clean and matched `origin/master`.
- Pre-deployment guarded checks found zero tracked high-confidence secret files,
  zero staged secret matches, and a clean `git diff --check`.

## Applied Turso schemas

The owner-approved, hash-locked, create-only migration tool applied these exact
reviewed artifacts:

1. `migrations/20260824_canonical_market_lineage_additive.sql`
   - SHA-256:
     `db10c366a7ef6adfdf6dbe6f4c39fe1fe4b3a2e573f393ed099e3b3028df542a`
   - 10 create-only statements.
2. `migrations/20260824_stock_prediction_audit_additive.sql`
   - SHA-256:
     `8ff5931429ceaba8713ec6d7f2efafa343292e0e4727b7835e782f31600d95c2`
   - 4 create-only statements.

No existing table or row was altered by either migration.

## Direct Turso readback

Canonical lineage:

- `market_canonical_policies`: exists, 8 columns, 0 rows.
- `market_canonical_bar_snapshots`: exists, 12 columns, 2 foreign keys, 0 rows.
- `market_canonical_bars`: exists, 20 columns, 2 foreign keys, 0 rows.
- `market_feature_recompute_runs`: exists, 13 columns, 3 foreign keys, 0 rows.
- `market_feature_recompute_keys`: exists, 4 columns, 1 foreign key, 0 rows.
- All five reviewed canonical indexes exist.

Prediction policy audit:

- `stock_prediction_decision_audits`: exists, 23 columns, 1 foreign key,
  0 rows.
- `stock_prediction_criterion_audits`: exists, 9 columns, 1 foreign key,
  0 rows.
- Both reviewed audit indexes exist.
- The live schema text independently contains
  `CHECK (order_authorized = 0)`.

## QA and service evidence

- Post-deployment protected repository suite: **251 passed**.
- Concurrent model/ingestion/order writers: **0**.
- Dashboard: HTTP **200**.
- `ag-sniper.service`: inactive and disabled.
- `antigravity-nightly.timer`: inactive and disabled.
- `antigravity-qa-watchdog.timer`: inactive and disabled.

## Capital-safety statement

No model was fitted. No recommendation, scorecard, policy-audit row, pending
order, execution plan, ledger row, or trade was created. No trading or nightly
service was activated. Capital was not at risk.

The new tables are empty governance structures only. Canonical-bar writes,
feature recomputation, model execution, prediction-audit writes, recommendation
generation, and execution each remain separately gated and require their own
evidence and approval.
