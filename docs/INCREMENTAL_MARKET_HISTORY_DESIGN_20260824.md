# Incremental Canonical Market History — Migration Design (2026-08-24)

## Target behavior

1. Seed historical bars once.
2. Ingest one newly completed exchange session per governed stock and ETF.
3. Preserve each provider observation as immutable revision evidence.
4. Select one canonical revision per `(ticker, session)` using an explicitly
   approved provider order and an evidence cutoff.
5. Append new keys and replace only keys whose source hash changed.
6. Recalculate only features affected by appended/revised sessions.
7. Perform a full-history fetch only after evidence of corruption, an unresolved
   provider discrepancy, or an explicitly approved recovery—not by schedule.

## Existing evidence reused

Turso already contains immutable tables `market_eod_ingestion_runs` and
`market_eod_bar_revisions`. Readback on 2026-08-24 proved:

- Complete runs: `2`
- Provider/mode: `TIINGO_EOD` / `DAILY_DELTA`
- Stored revision rows: `479`
- Distinct instruments: `472`
- Evidence session: `2026-08-21`
- Repeated ticker/session keys: `7`
- Repeated keys with conflicting source hashes: `0`
- Deterministically selected canonical rows: `472`

The repeated observations are identical re-observations, not value changes.

## Implemented research primitive

`canonical_market_history.py` now provides side-effect-free functions to:

- require a preregistered provider priority;
- reject non-complete runs, invalid hashes, invalid timestamps, and providers
  missing from the policy;
- apply an evidence cutoff;
- select the latest eligible revision within the highest-priority provider;
- reconcile new evidence into canonical history;
- identify appended, genuinely revised, and unchanged keys.

The module does not choose which provider outranks another and performs no
Turso write. Provider precedence is a governance decision that requires
separate approval and evidence.

## Required next gates

1. Approve the canonical provider-selection policy.
2. Add and review a narrow Turso canonical-selection schema or deterministic
   cutoff view; do not duplicate full bar values in daily snapshots.
3. Prove a one-time baseline plus deltas reproduces the current validated
   `2026-08-21` market snapshot for raw bars and explain every feature-level
   difference.
4. Implement bounded affected-window feature recomputation, including corporate
   action back-adjustment impacts.
5. Only after reconciliation passes, replace the nightly full-history rebuild.
