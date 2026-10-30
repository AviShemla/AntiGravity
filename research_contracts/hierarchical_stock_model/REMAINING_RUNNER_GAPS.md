# Remaining S08 hierarchical runner gaps

The isolated implementation is **TESTED as a pure selection and backend
boundary**, not a deployed or observed model runner.

1. The imported `antigravity/stock_model_dataset.py` uses the current canonical
   percent fields (`y_return_pct`), but its feature builder still interprets
   tuple position as lag depth. Its universe/preflight readers expose positional
   `lag1_ticker` through `lag5_ticker`. This must not be used for the independent
   lag-1–7 contract. Integration must use the already governed normalized-edge
   source after fresh canonical-repository verification.
2. The fixture selector explicitly freezes a Fisher-z two-sided association
   test plus global BH-FDR. S07 binds topology, lags, depths, folds, sampler, and
   model configuration hashes, but the inspected preregistration surface does
   not independently prove this exact association-test identity. The real
   runner must bind the exact approved selection-test artifact; this fixture
   method must not be silently adopted as production research semantics.
3. This package intentionally requires an injected backend and does not import
   PyMC. A real backend still needs implementation and tests proving the graph
   bound by `graph_contract_sha256`, the exact preregistered numeric priors and
   sampler, deterministic seeds, partial pooling, 474-target/four-fold
   reconciliation, and diagnostic extraction.
4. Restart-safe append-only checkpoints, immutable release construction,
   resource enforcement, secure launch, quarantine, and terminal independent
   readback remain governed by `model_fit_contract_impl` but are not yet wired
   to a real backend.
5. No database writer is authorized. Posterior persistence to Turso remains
   separately gated on a reviewed append-only schema/writer scope and must not
   be inferred from this implementation.

The next safe implementation step is to bind this boundary to the canonical
normalized-edge reader and implement a fixture-only PyMC backend behind the
injected interface. A real run remains **NOT RUNNING** until the exact S07
evidence, authorization, immutable release, resources, and ingestion buffer all
pass the separate execution contract.
