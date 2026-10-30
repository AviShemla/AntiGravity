# Governed successor stock-model preregistration v2

This package freezes and independently audits a research-only preregistration.
It performs no model fit, prediction, recommendation, order, ETF, or trading
operation. Network and Turso access exist only in the separately bounded
SELECT-only readback producer; the contract, binder, runtime, and auditor have
no database client.

## Evidence boundary

The contract keeps these identities separate and rejects substitution among
them:

- the immutable baseline final-manifest file SHA-256;
- the immutable v4 independent-audit file SHA-256;
- the embedded v4 audit-evidence SHA-256;
- the preregistration contract-envelope SHA-256;
- a fresh source-readback file SHA-256 and its embedded evidence SHA-256; and
- a separate canonical current-readback artifact SHA-256.

Immutable and current evidence must reconcile exactly:

- 474 tickers;
- 1,896 folds;
- 56,880 out-of-sample observations;
- six zero baseline side-effect counters; and
- all eight exact zero downstream-table counters emitted by the v4 auditor.

The perpetual current-readback contract requires a newly observed proof no
more than five minutes old. Retimestamping, caller-supplied lineage, stale
proof reuse, and raw/embedded digest substitution are rejected.

## Frozen research geometry

- topology: independent ticker/lag edges;
- candidate lags: 1 through 7;
- candidate depths: 1 through 5;
- claim: observational predictive association, never causal proof;
- full input calendar: exact 1,246-session date sequence;
- model calendar: exact last 416-session slice of that sequence;
- training width: 289 sessions;
- four non-overlapping 30-session outer tests;
- 30-session step;
- seven-session purge; and
- minimum fit observations: 126.

The governed sampler is PyMC NUTS with at least four chains, 1,000 posterior
draws, 1,000 tuning draws, target acceptance at least 0.90, and a fixed
nonnegative integer seed. The exact selected sampler configuration is
content-hashed in every preregistration.

## Perpetual SELECT-only readback

The producer performs exactly five governed readbacks:

1. the exact 1,246-session calendar;
2. all three validated screening-run and snapshot identities;
3. the common 474-ticker universe;
4. downstream schema; and
5. eight downstream counts bound to the proposed model Git commit.

It persists a write-once source-evidence file and a separate canonical
readback artifact under root-owned mode-0700 output directories. Every input
is a root-owned, mode-0600, single-link regular file. The independent verifier
recomputes both byte identities and replays the immutable lineage, chronology,
schema, coverage, zero-output, and freshness gates.

## Required integration sequence

1. Independently verify the immutable v4 final manifest and audit, including
   raw file identities, embedded digests, executor commit, artifact closure,
   chronology, exact coverage, and zero-output evidence.
2. Run the bounded producer against Turso with SELECT-only credentials and
   persist both current evidence layers exactly once.
3. Independently verify both current files and their cross-binding before any
   binder input is accepted.
4. Invoke `stock_preregistration_runtime.py` with the immutable files, both
   current files, the exact proposed model Git commit, observation timestamp,
   and unique run ID.
5. Persist the preregistration exactly once in a root-owned, mode-0600,
   single-link artifact.
6. Invoke `audit_stock_preregistration_manifest.py` against the persisted
   manifest and all four source artifacts while the current proof is fresh.
7. Treat `PASS` only as a preregistration result. The manifest always records
   `fixture_only=true`, `model_fit_authorized=false`,
   `model_fit_started=false`, and zero downstream outputs. It has no `READY`
   state.
8. Require a separate reviewed execution contract to reproduce every frozen
   identity, chronology, purge, calendar, sampler, output, and safety gate
   before any later model runner may start.

Prediction persistence, recommendations, orders, trading, snapshot
validation/promotion, and ETF-prior generation remain outside this package
and unauthorized.
