# Stock decision gates and sizing comparison — 2026-08-24

## Status

Research/shadow only. This policy evaluator performs no I/O and cannot create
recommendations, pending orders, or ledger entries. Existing broker behavior
is unchanged.

## Separation of responsibilities

### Hard evidence gates

Only evidence-integrity conditions can return `NO_TRADE` before sizing:

- market snapshot is not validated;
- controlled universe is not approved;
- source and prediction dates do not align;
- model run is incomplete;
- sampler QA failed;
- research promotion is not approved; or
- an evidence-backed quarantine remains active.

Each failure is returned as an explicit reason code. Legacy blacklist state is
reported in the AG lane but is not silently inherited as a new hard gate.

### Model decision

The raw posterior is always reported. The comparison contains:

- the observed AG scorecard/persona outcome;
- the strict posterior-interval Codex hypothesis; and
- the balanced mean-probability hypothesis.

No lane hides a prediction because a later allocation is zero.

### Position sizing

AG's observed Kelly calculation and fixed fallback remain visible in the AG
lane. The shadow lane:

- subtracts the recorded round-trip cost from expected return;
- keeps allocation at zero for non-positive net return, non-positive risk, or
  non-positive Kelly;
- never substitutes AG's fixed 10%/15% allocation fallback; and
- retains the existing persona Kelly multiplier and allocation cap solely to
  make the comparison controlled.

### VIX

AG's discontinuous VIX steps remain visible. The shadow hypothesis reuses the
same persona transition ranges but interpolates continuously from `1.0` to a
`0.25` sizing floor. VIX is therefore a sizing observation, not an evidence
gate, and cannot upgrade a `HOLD`/`NO_TRADE` result.

The continuous function and its floor are hypotheses to test out of sample,
not approved paper or production settings. Promotion requires calibration,
turnover/cost, drawdown, and trade-frequency comparison against the AG lane.

## Required per-prediction audit

For each future stock scorecard, persist or render the following only after a
validated model run exists:

1. source snapshot and model lineage identifiers;
2. posterior mean and interval, expected return, expected risk, and costs;
3. every hard-gate result and reason;
4. AG, strict, and balanced directional outcomes;
5. AG and shadow VIX multipliers;
6. AG and shadow Kelly/allocation fractions; and
7. quarantine/blacklist evidence and final non-execution reason.
