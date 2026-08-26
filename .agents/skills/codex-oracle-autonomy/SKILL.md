---
name: codex-oracle-autonomy
description: Autonomously advance the Codex-led Oracle migration and recover approved research, ingestion, governance, and infrastructure work from blockers using evidence-gated successor transitions, safe parallelism, persistent Vultr workers, and strict production/trading boundaries. Use for Oracle migration work, liveness monitoring, recovery, or status reporting; do not use for unrelated projects.
---

# Codex Oracle Autonomy

Advance the Codex-controlled, Turso-backed Oracle system without waiting on the
user for routine work already inside the approved research or migration scope.
Legacy AntiGravity artifacts are inputs to audit, not the target architecture or
active agent.

## Successor-work transition

Treat `BLOCKED`, `STALLED`, `FAILED`, and `NO_QUALIFYING_OUTPUT` as transition
events, not terminal monitoring states.

1. Preserve current evidence and prevent duplicate or deterministic retries.
2. Enumerate the immediate successor graph and classify every action:
   - `SAFE_NOW`: read-only inspection, tests, additive/reversible code changes,
     recovery within existing authority, or research preparation that preserves
     all gates.
   - `DEPENDENCY_BLOCKED`: technically impossible until named evidence or an
     upstream result exists.
   - `APPROVAL_REQUIRED`: destructive work, new credentials, schema application,
     snapshot validation/promotion, weakened safeguards, model-to-order
     activation, trading, email, or another material external commitment.
3. Start every technically independent `SAFE_NOW` action within available
   capacity. Use bounded subagents for independent technical work and persistent
   Vultr workers for long jobs. Never create parallel duplicate writes.
4. Stop only when no `SAFE_NOW` action remains or each remaining safe action is
   attached to a freshly verified persistent worker and durable checkpoint.
   Unlaunched safe work is an orchestration incident and must be reported.

Never respond to `NO_QUALIFYING_OUTPUT` by relaxing thresholds, changing windows,
features, hypotheses, eligibility, or substituting a model family to obtain a
better result. Preserve the failed run unchanged. A successor research family
must be separately preregistered and frozen before execution.

Before parallel launch, read CPU, memory, I/O, and applicable database-rate
capacity. Guarded ingestion owns priority; do not create contention with it.
Use isolated fixtures for safe local tests when production-host capacity is not
available.

Research model fitting is `SAFE_NOW` only when the exact run was already
authorized, preregistered, immutable inputs exist, and all preflight gates pass.
Otherwise implementation and fixture testing may proceed, but fitting is
`DEPENDENCY_BLOCKED` or `APPROVAL_REQUIRED`. Append-only Turso research writes
are `SAFE_NOW` only with an existing approved schema, exact writer scope,
idempotency key, and run authorization; all other Turso writes require approval.

## Evidence and liveness

- Apply `DESIGNED`, `IMPLEMENTED`, `TESTED`, `DEPLOYED`, `OBSERVED`, and
  `VERIFIED` literally. Never collapse them into "fixed" or "complete."
- Re-read authoritative Git, systemd, durable logs/checkpoints, and Turso data;
  never infer continuity from a prior report.
- A running claim requires host, unit/PID, command, immutable code identity,
  start time, checkpoint path, current marker, and checkpoint age.
- Long work must be restart-safe and idempotent on Vultr. Declare its maximum
  checkpoint interval and classify it `STALLED` when exceeded.
- Completion needs terminal state, exact output/count reconciliation, and
  independent readback. Percentages require named completed/total milestones;
  ETA requires measured checkpoint throughput.

## Oracle safety boundary

- Turso is the production source of truth. Never use CSV, Excel, SQLite, or
  Streamlit as a production source or fallback.
- Keep trading, recommendations, orders, email, sniper activation, and snapshot
  validation/promotion disabled unless Avi gives the required explicit scoped
  approval. Approval never waives hard safety gates.
- Research preparation may proceed in parallel with guarded ingestion only when
  it cannot alter the ingestion code/runtime, snapshot lifecycle, or production
  data.
- Additive code changes require an authoritative clean baseline, isolated file
  ownership, focused and regression tests, secret scan, rollback path, commit,
  push readback, and independent review proportional to scientific risk.
- Preserve exact snapshot, provider, universe, screening, code, configuration,
  sampler, and output lineage. No silent provider mixing or replacement.
- When repository rules are stricter, follow them. A repository rule cannot be
  used as an excuse to leave independent safe work unstarted.

## Reporting

Lead with current evidence and distinguish facts from unknowns. List active
workers separately from planned work. State `NOT RUNNING` when no persistent
worker exists. For every blocker, also state which safe successors were launched
and which require Avi.
