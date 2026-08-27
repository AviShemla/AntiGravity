# Governed successor stock-model preregistration v2

This package freezes and independently audits a research-only preregistration.
It performs no filesystem, network, Turso, model-fit, prediction,
recommendation, order, ETF, or trading operation.

## Evidence boundary

The contract keeps these identities separate and rejects substitution among
them:

- the immutable baseline final-manifest file SHA-256;
- the immutable v4 independent-audit file SHA-256;
- the embedded v4 audit-evidence SHA-256;
- the preregistration contract-envelope SHA-256;
- a new fresh-readback file SHA-256; and
- that readback's embedded audit-evidence SHA-256.

Both immutable and fresh audit evidence must reconcile exactly:

- 474 tickers;
- 1,896 folds;
- 56,880 out-of-sample observations;
- six zero baseline side-effect counters; and
- all eight exact zero downstream-table counters emitted by the v4 auditor.

A fresh readback must be independently produced, cannot be retimestamped, must
follow the immutable audit, and must be no more than one hour old when the
contract is created or re-audited.

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

## Required integration sequence

1. Independently read the immutable baseline artifacts and verify their raw
   file identities, canonical embedded digests, executor commit, exact schemas,
   artifact closure, chronology, coverage, and zero-output evidence.
2. Independently reread the validated baseline lineage and exact 1,246-session
   calendar from Turso using SELECT-only access.
3. Produce a fresh independent v4 completion audit and preserve both its raw
   file SHA-256 and embedded evidence SHA-256.
4. Build the preregistration through the pure binding adapter using the exact
   current model-code Git commit, immutable audit, fresh readback, universe,
   calendars, configuration, and sampler identities.
5. Persist the preregistration exactly once in a root-owned, mode-0600,
   single-link artifact before any model fit may be considered.
6. Produce a second fresh readback and independently replay every semantic
   preregistration validator against the persisted artifact.
7. Treat `PASS` only as a preregistration result. The manifest always records
   `fixture_only=true`, `model_fit_authorized=false`, `model_fit_started=false`,
   and zero downstream outputs. It has no `READY` state.
8. Any later model runner requires a separate, reviewed execution contract and
   must reproduce the frozen identity, chronology, purge, calendar, sampler,
   output, and safety gates before starting computation.

Prediction persistence, recommendations, orders, trading, snapshot promotion,
and ETF-prior generation remain outside this package and unauthorized.
