# Baseline audit-only v2 (isolated proposal)

This directory contains a pure, fixture-tested successor for independently
auditing the already completed full-universe baseline producer artifacts.

It intentionally does **not**:

- contact Turso or own a database client;
- rerun the baseline producer or generate predictions;
- write evidence, mutate snapshot/dataset lifecycle state, deploy, or authorize
  a successor;
- claim that the repaired verifier belongs to the old producer release.

The producer closure is pinned by its original Git commit, executor manifest,
final manifest, deterministic evidence, lineage, and checkpoint bytes. A new
verifier release is separately pinned by an external runner. The release
manifest is required to say `execution_authorized=false`, `write_scope=NONE`,
and `read_scope=EXACT_THREE_SELECTS_FINAL_PHASE_ONLY`.

The final runtime boundary remains deliberately absent. It must establish the
authenticated `codexops`/Turso identity, root-owned release and external pin,
exact three SELECT statements, freshness, timeouts, and zero writes before
passing readback results to `finalize_live_audit`. Only after that independent
readback can the baseline milestone move beyond `TESTED`.

Rollback is deletion of this isolated directory; it has no external side
effects.
