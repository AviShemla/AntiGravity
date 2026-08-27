# S08 current runner gap audit

Evidence inspected in the imported workspace on 2026-08-27; no network,
database, deployment, service, or fit operation was performed.

## Stop-the-line findings

1. There is no `antigravity/stock_hierarchical_pymc_core.py`. The staged
   `work/stock_hierarchical_cohort.py` imports that module, and its focused test
   terminates at import with `ModuleNotFoundError`. Therefore no executable
   hierarchical fitter closure exists in this workspace.
2. The staged cohort fixture uses `StockModelDataset.y_return_pp`, while the
   current canonical class in `antigravity/stock_model_dataset.py` defines
   `y_return_pct`. It also constructs `StockPosteriorEvidence` with
   `expected_return_pp_mean/std`, while
   `antigravity/stock_pymc_core.py` defines
   `expected_return_pct_mean/std`. Even after supplying the missing module, the
   staged runner/test contract is incompatible with current model types.
3. `antigravity/stock_pymc_core.py` is a per-ticker fitter. It does not prove
   the preregistered independent-edge hierarchical model, full 474-target/four-
   fold execution, training-only edge selection, append-only checkpointing, or
   idempotent resume required by S08.
4. No reviewed immutable S08 model release, dependency lock, executable
   entrypoint, secure launcher, or completion auditor is present in the
   inspected workspace. Consequently the new authorization contract cannot be
   populated with real closure evidence yet.
5. The verified S07 preregistration intentionally records
   `model_fit_authorized=false`. A separate exact, content-addressed run
   authorization record is still required. Broad migration authority must not
   be silently converted into permission for a different model, sampler,
   threshold, hypothesis, or downstream use.
6. No approved append-only Turso posterior writer/schema was established by
   the inspected artifacts. The execution contract therefore freezes database
   write scope to `NONE`; changing that scope remains separately gated.

## Safe successor sequence

1. Reconcile the percent-versus-percentage-point model type contract and add the
   missing hierarchical fitter with synthetic lag recovery, null/no-signal,
   hierarchy, training-only selection, multiple-testing, and lookahead tests.
2. Add a restart-safe 474-target/four-fold runner whose append-only filesystem
   checkpoints bind the exact S07 preregistration, immutable input data, code,
   configuration, sampler, and deterministic seed.
3. Add an independent terminal auditor covering exact target/fold/ticker and
   lag/depth geometry, sampler diagnostics, cutoffs, and zero downstream
   outputs.
4. Build and secret-scan a root-owned immutable release with an exact dependency
   lock and Python identity; then test crash/resume, duplicate-writer rejection,
   resource ceilings, checkpoint freshness, quarantine, and rollback.
5. Only then bind fresh S07 readback, current capacity/ingestion evidence, and
   an exact run authorization into `AUTHORIZED_NOT_STARTED`. A separate secure
   launcher must independently audit the artifact before starting one process.

Until those steps pass, the honest S08 state is **TESTED EXECUTION-CONTRACT
IMPLEMENTATION; MODEL FIT DEPENDENCY-BLOCKED AND NOT RUNNING**.
