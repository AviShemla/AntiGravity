# AntiGravity Recovery Checkpoint — 2026-08-25 Model Governance

## Evidence scope

- Mode: FROZEN/RESEARCH.
- Canonical Vultr Git worktree: `/home/codexops/codex_git/AntiGravity`.
- Verified baseline commit before this checkpoint: `af910c95965c0d9a2e5e9bea665720c7df890341`.
- GitHub `origin/master` matched that baseline before checkpoint creation.
- Canonical worktree was clean before the schema operations.
- No credentials are included in this checkpoint.

## Applied Turso additive schemas

### model_input_approval_events

- Migration: `migrations/20260822_model_input_approval_events_additive.sql`
- Reviewed SHA-256: `0209515c539025db68fa626424a00cd75d01ad40458b2d14ae25a4fdd04e4345`
- Result: two CREATE-only statements applied.
- Verified objects: `model_input_approval_events` and `idx_model_input_approval_effective`.
- Verified row count after application: 0.

### model_run_inputs

- Migration: `migrations/20260822_model_run_inputs_additive.sql`
- Reviewed SHA-256: `e204c71f5f2919b6ee3f11588a34d6d4c6578b39947850301d643a513ded1e6e`
- Result: two CREATE-only statements applied.
- Verified objects: `model_run_inputs` and `idx_model_run_inputs_snapshot`.
- Verified row count after application: 0.

## Protected Turso readback

Counts were identical before and after both schema operations:

- `capital_ledgers`: 299
- `pending_orders`: 4
- `model_input_snapshots`: 5
- `model_runs`: 0
- `model_scorecards`: 0
- `model_input_approval_events`: 0
- `model_run_inputs`: 0

Snapshot `market_features_2026-08-24_98b55d95327ad947` remained `STAGING`; it was not validated or promoted.

## Service readback

- `ag-uvicorn.service`: active
- `ag-vix.service`: active
- `ag-sniper.service`: inactive and disabled
- `antigravity-nightly.timer`: inactive and disabled
- `antigravity-qa-watchdog.timer`: inactive and disabled

No model, recommendation, order, email, deployment, snapshot promotion, or trading activation was performed.

## Independent call-graph audit

Two bounded read-only specialist audits independently confirmed:

1. No production stock execution path calls `build_stock_model_preflight`.
2. No production ETF execution path calls `build_etf_model_preflight`.
3. `save_model_run`, `save_model_scorecard`, and `save_etf_prior` have no production callers.
4. Modern `stock_pymc_core` and `etf_pymc_core` are not production-wired.
5. Legacy orchestrators still reach exporters that use forbidden CSV/Excel fallbacks, dummy/quarantine outputs, direct market downloads, and direct legacy-table writes.

Therefore sniper, nightly, QA, and model execution remain blocked.

## Approved next implementation

The owner approved continued implementation of a fail-closed model path:

1. Add a canonical stock runner.
2. Atomically create a `model_runs` record and bind the exact validated MARKET_FEATURES and STOCK_UNIVERSE snapshots in `model_run_inputs`.
3. Recheck status, source session, cutoff, and checksums inside the write transaction.
4. Invoke the pure PyMC core only after successful preflight and binding.
5. Apply diagnostic and eligibility gates.
6. Permit scorecards only for runs with proven input bindings.
7. Add and review database-boundary guards.
8. Block legacy production entrypoints.
9. Repeat the design for ETF with auditable stock-derived prior lineage.

Production deployment, applying any additional guard migration, validating/promoting snapshots, running models, creating recommendations/orders, and activating services remain separate verified steps.
