# Canonical S11 comparison gate candidate

This isolated candidate consumes the canonical `posterior_evaluation` request,
artifact, row, boundary, audit, JSON, and artifact-digest semantics unchanged.
It does not create another lineage model and never derives or reinterprets
`universe_sha256`; that value remains opaque inside canonical lineage.

The current canonical builder is explicitly fixture-only but emits review rows
when fixture outcomes exist. The new gate independently reruns the canonical
fixture auditor, records the canonical artifact digest, and exposes **zero
accepted comparison rows**. Fake acceptance input cannot bless fixture output.
The canonical source artifact retains its existing inherited-AG and
proposed-Codex comparison fields for fixture QA, while no row crosses the real
accepted-comparison boundary.

The additive blocked-audit manifest makes those fixture-QA rows independently
rebuildable one prediction at a time. Each row embeds the exact canonical
comparison row (raw Bayesian output, inherited-AG decision/reasons, proposed
Codex decision/reasons, hard safety gates, and sizing adjustments) and binds it
to the complete fixture artifact, canonical lineage, posterior record,
decision outputs, hard-gate digest, and validated derivation evidence. The
manifest always records zero accepted predictions, `population_authorized`
false, and the exact fixture-only zero-operational boundary. It is audit
scaffolding, not a substitute for the missing accepted posterior artifact.

The candidate also supplies the prerequisite validator for future accepted
rows. It binds each exact canonical row to its posterior-record digest,
immutable AG and Codex evaluator releases, immutable policy artifacts,
canonical AG/Codex output digests, independent replay/audit digests, evaluation
timestamps, and a replay audit observed within five minutes of envelope
construction. Retrospective AG-rule and Codex replays may execute after the
historical cutoff only when their allowlisted input-bundle digest proves every
input was available by the cutoff and the effective-as-of timestamp is not
later than the cutoff; realized outcomes, decisions, gates, and sizing outputs
are not members of that digest. A genuinely recorded historical AG decision
instead requires its original pre-cutoff recorded-at timestamp and immutable
source-record hash. Old AG provenance is a required enum:
`HISTORICAL_RECORDED_DECISION` and `HISTORICAL_RULE_REPLAY` hash differently and
cannot be conflated. This validator checks structural linkage and chronology;
it does not read or independently recompute the referenced audit bytes. A
future independent auditor must perform that recomputation before population.
This validator does not itself authorize population.

## Exact remaining gap

Canonical S10 does not yet define a non-fixture posterior artifact type and an
independent acceptance auditor whose output can be consumed here. Consequently
the accepted-population path is intentionally absent, not simulated. Adding it
requires canonical review of that S10 artifact/auditor first. Once available,
the smallest follow-up is a second builder that accepts only its audited result,
reuses the existing canonical `PredictionEvidenceRow`, and binds its digest with
`canonical_json`; it must not accept `build_fixture_posterior_artifact` output.
That builder must also require the decision-derivation validator result; opaque
policy hashes or caller-injected AG/Codex objects are insufficient.

No database, network, model fit, deployment, recommendation, order, ETF output,
promotion, threshold, or persistence behavior exists in this candidate.

