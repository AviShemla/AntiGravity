# Codex Oracle migration-plan validation contract

This directory contains an execution-free, fail-closed validator for a
machine-readable migration plan. It validates the plan's graph and declared
controls; it does **not** treat a valid plan as proof that any migration stage
has run.

## Integration contract

The architect's plan must be adapted to `codex-oracle-migration-plan/v1` with:

- top-level `plan_id`, exact Codex/Turso target identity, the exact safety
  policy, a non-empty `stages` array, and `successor_ownership`;
- one stable, unique stage `id` per stage and acyclic `dependencies`;
- one of the literal evidence stages `DESIGNED`, `IMPLEMENTED`, `TESTED`,
  `DEPLOYED`, `OBSERVED`, or `VERIFIED`;
- explicit integer `progress.numerator` and `progress.denominator`; no inferred
  percentage and no nullable denominator;
- structured `test`, `observe`, and `readback` gates, with evidence references
  whenever a gate is satisfied;
- structured operations with capability identifiers, rather than executable
  shell embedded in the plan;
- an explicit per-stage filesystem boundary with enumerated write roots,
  resolved-target verification, and broad recursive operations forbidden;
- reversible, idempotent and bounded `autofix`, a no-data-loss `rollback`, and
  stale-checkpoint recovery that preserves evidence, prevents duplicates and
  resumes from a checkpoint;
- explicit success/failure/stall successor IDs; per-transition evidence and
  safety gates (including independent completion readback for success); and
  exactly one named owner for every referenced successor;
- Turso for all research or production data; isolated fixtures are permitted
  only for isolated tests;
- the exact inactive/disabled invariants for `ag-sniper.service`,
  `antigravity-nightly.timer`, and `antigravity-qa-watchdog.timer`.

Unsafe capabilities (trading, recommendations, orders, email, sniper
activation, snapshot validation/promotion, production schema application, and
safeguard weakening) are rejected from every automatic context. A plan can
represent a manual, explicitly approved future step only as an
`APPROVAL_REQUIRED` operation with `automatic: false` and a scoped
`approval_ref`. Approval is structural metadata, not authorization to execute.

## Validation

```powershell
python -m unittest discover -v -s migration_plan_validation_impl -p 'test_*.py'
python -m migration_plan_validation_impl.migration_plan_validator plan.json
```

The CLI emits one JSON validation report and exits `0` for a valid plan or `2`
for a malformed/invalid plan. It does not echo malformed input.

The orchestration layer must call `assert_valid_plan(plan)` before accepting a
plan and must separately authenticate the plan artifact, validate each evidence
reference, and enforce the declared controls at runtime. A zero-issue result is
only `TESTED` evidence for plan structure, never `OBSERVED` or `VERIFIED`
evidence for migration execution.
