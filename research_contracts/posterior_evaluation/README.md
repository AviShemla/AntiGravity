# Fixture-only posterior evaluation successor

This isolated successor defines the safe-now contract for Codex Oracle
workstreams 6 and 7. It is **implemented for in-memory fixtures only**. It does
not claim that a posterior exists, that a model converged, or that production
integration is complete.

## Contract

`posterior_evaluation_contract.py` requires and preserves:

- immutable dataset, snapshot, universe, code, configuration, sampler, seed,
  run, observation-time, posterior-available-at, and prediction-cutoff lineage;
- an exact ordered immutable session calendar and calendar SHA-256, plus outer
  walk-forward fold indices whose training/test/purge/overlap counts are
  recomputed rather than trusted; every fold retains at least 126 training
  sessions, a seven-session purge, zero overlap, and non-overlapping test ranges;
- UTC availability timestamps for every immutable session; each posterior must
  be no earlier than the latest eligible source/fold-test input timestamp and
  must equal or precede the policy-derived prediction cutoff. The lineage
  observation timestamp must be at or after every bound calendar, posterior,
  cutoff, hierarchy, preregistration, baseline-audit, validation, completion,
  and quarantine timestamp. Hierarchy evidence must precede preregistration,
  the verified baseline audit must precede the first posterior, no posterior
  may predate any snapshot/universe or governance prerequisite, and model
  completion must follow every posterior;
- a frozen ticker/persona-to-hierarchy registry whose identity and SHA-256 are
  bound in lineage; caller-supplied hierarchy paths must match it exactly;
- an exact sampler policy (name, chains, posterior/tuning draws, and parameter
  set), checked against actual diagnostic dimensions, parameter-level
  R-hat/bulk-ESS/tail-ESS, and chain-level divergences and BFMI;
- one complete ticker/persona/date panel of posterior outcomes with raw mean,
  standard deviation, 5%-95% interval, expected return and uncertainty, risk,
  realized return, and research-only allocation;
- deterministic calibration, transaction-cost, terminal-close, compounded
  return, and drawdown evaluation; and
- exactly one review row per posterior containing raw Bayesian output, the
  recorded inherited AG decision and reasons, the recorded proposed Codex
  decision and reasons, the exact governed seven-gate set with canonical reason
  codes, and every sizing adjustment.

All governed numeric inputs use strict domains: counts require exact `int`
values and continuous measurements require exact finite `float` values.
Booleans, strings, decimal-like coercions, NaN, and infinities are rejected as
`ContractError` before arithmetic or serialization. Derived calibration,
convergence, cost, return, and drawdown fields are validated under the same
domains before they enter an artifact.

Safety-gate booleans are never accepted from the caller. Snapshot validation,
universe approval, completed-run identity, temporal alignment, sampler QA, and
quarantine status are derived from bound evidence. Research-promotion
eligibility is derived from the immutable fixture boundary and is therefore
false. A converged fixture is `PROMOTION_BLOCKED`; a diagnostic failure is
`DIAGNOSTIC_BLOCKED`, and every row receives the same failed sampler gate and
reason. The contract has no `READY` state.

Quarantine non-membership is not sufficient by itself. The frozen quarantine
registry must have been observed after model completion and after every bound
posterior. If it is stale, every evidence row fails `NOT_QUARANTINED` with
`QUARANTINE_EVIDENCE_NOT_APPLICABLE`, so the artifact remains blocked.

No posterior rows returns `ABSENT_POSTERIOR_BLOCKED` with
`ABSENT_POSTERIOR_OUTPUT`; it never fabricates diagnostics, metrics, or evidence
rows. Failed convergence retains the research measurements but returns
`DIAGNOSTIC_BLOCKED`. Every artifact carries a hard boundary asserting fixture
only, no database/network/model fit, no created recommendation/order/ETF
output, no operational eligibility, and no promotion authority. Its
`request_sha256` binds every normalized input row, including folds, diagnostics,
outcomes, and recorded comparison evidence. Nested input collections are copied
to immutable tuples before hashing. `audit_fixture_posterior_artifact` reruns the
full semantic build and rejects modified status, evidence, metrics, lineage,
counts, review flags, or operational boundary even if a caller recomputes a
digest. Lineage also requires an exact 40-character Git commit plus immutable
preregistration and baseline-audit identities and SHA-256 digests.

## Integration plan

1. Independently review this isolated contract against the canonical Oracle
   policy and migration schema; retain it outside production until accepted.
2. Adapt the future authorized posterior producer to emit the exact immutable
   request fields without changing this evaluator or bypassing its blocked
   states.
3. Add a read-only adapter for an approved immutable research snapshot and a
   separate append-only persistence adapter only after schema and writer scope
   receive explicit approval. Keep both adapters outside this pure module.
4. Run the contract on a preregistered walk-forward stock posterior, reconcile
   exact expected/actual folds and predictions, and independently read back the
   artifact digest and every evidence row.
5. Only after accepted convergence and evaluation evidence may a separately
   approved promotion workflow consume the artifact. ETF-prior construction,
   recommendation/order creation, and trading remain outside this contract.

Rollback is deletion of this isolated directory; it changes no canonical or
runtime artifact.
