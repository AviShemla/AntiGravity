# Codex Oracle Migration — Canonical Evidence-Gated Execution Plan

Plan ID: `codex-oracle-migration-v1`
Plan status: `CANONICAL_BASELINE`
Target: a fully Codex-controlled, Turso-backed Oracle research and paper/shadow system.
Legacy AntiGravity (AG) code, rules, units, and artifacts are migration inputs only; they are not the target architecture or active agent.

## 1. Purpose and completion definition

This plan converts the migration into a finite, testable sequence. It prevents the two failure modes that have repeatedly wasted time:

1. a technical step fails or reports red and the work remains in monitoring instead of transitioning to a safe successor; and
2. a component is described as fixed before its deployed runtime behavior and independent readback prove the claim.

Migration is complete only when every stage in this document has an `exit_proof` artifact whose identity is independently read back, all required stages have reached `VERIFIED`, the final acceptance matrix has no unresolved critical contradiction, and the temporary nightly continuity job plus retired legacy units are independently proven disabled. Passing unit tests, a zero shell exit, or an elapsed timer is never sufficient by itself.

## 2. Non-negotiable operating rules

- **Evidence states are literal:** `DESIGNED -> IMPLEMENTED -> TESTED -> DEPLOYED -> OBSERVED -> VERIFIED`. A stage may move backward when its evidence expires, its artifact identity changes, or contradictory evidence appears. Percent complete and evidence maturity are separate quantities.
- **Turso is the production source of truth.** CSV, Excel, SQLite, and Streamlit are prohibited as production sources, caches, write targets, or fallbacks.
- **Fail closed:** missing, stale, conflicting, non-finite, implausible, or lineage-incomplete input stops downstream work. It never triggers silent substitution, threshold relaxation, or model-family changes.
- **No unauthorized production action:** no recommendations, approval events, orders, trading, email, sniper activation, snapshot validation/promotion, production schema application, or weakened safeguard without Avi's explicit written and scoped approval.
- **No blind retries:** before retrying, preserve the failed InvocationID, command, immutable code identity, journal, durable checkpoint, Turso state, and exact error. Deterministic retries are prohibited until the cause is repaired or a bounded transient retry policy explicitly applies.
- **Successor transition is mandatory:** every `FAILED`, `STALLED`, `BLOCKED`, or `NO_QUALIFYING_OUTPUT` state causes immediate classification of the successor graph as `SAFE_NOW`, `DEPENDENCY_BLOCKED`, or `APPROVAL_REQUIRED`. Every independent `SAFE_NOW` action is launched within verified resource capacity. Unlaunched safe work is an orchestration incident.
- **Guarded ingestion owns resource priority.** Before parallel work, re-read CPU, memory, I/O, systemd state, and database-rate capacity. Research workers must yield or pause before contention can threaten ingestion.
- **One writer per idempotency key:** systemd runtime locks, Turso uniqueness constraints, write-once artifacts, and run IDs prevent duplicate snapshots, runs, outputs, or ledgers.
- **Long jobs are persistent and observable:** each has a systemd unit, InvocationID, PID, exact command, immutable Git/deployment identity, start time, root-owned durable checkpoint, measured maximum checkpoint interval, CPU/memory, and Turso readback.
- **Changes are reversible and secret-free:** clean baseline, isolated ownership, focused tests, regression tests, static/secret scan, rollback path, commit, push readback, immutable deployment identity, and independent review are required.
- **No causal overclaim:** observational lag screening is predictive screening, not causal proof. Independent ticker/lag edges use lags 1–7 and model depth 1–5; no forced `5 -> 4 -> 3` chain.
- **Research progression:** research -> backtest -> paper/shadow -> live. This plan ends at verified paper/shadow readiness unless Avi separately approves a later live-governance plan.

## 3. Current incident baseline (evidence snapshot, not continuity proof)

These facts define the initial plan state. Every execution cycle must re-read live evidence before relying on them.

- The guarded 2026-08-26 extraction created STAGING snapshot `market_features_2026-08-26_911350a3784e5b1d` with 587,184 reconciled rows, 474 feature tickers, and 476 provider-lineage entries (474 feature tickers plus `^TNX` and `^VIX`). It remained unvalidated and unpromoted, with zero approval events and zero screening runs.
- The primary ingestion unit exited nonzero during postflight despite the later independent reconciliation. The identified false-red contract compared the 476-entry provider lineage to the 474 feature-ticker count instead of comparing exact sets including the two required macro tickers. A pure fail-closed reconciliation patch and six focused tests exist locally; this is `TESTED`, not `DEPLOYED`, `OBSERVED`, or `VERIFIED`.
- Successor baseline v1 failed deterministically before creating durable files: InvocationID `d19062f22c4b4be1ba39424e8aed2c8a`, 00:53:52–00:53:54Z, exit 1. A bare HTTPS Turso URL was passed to a client requiring `/v2/pipeline`. Prevention requires one shared endpoint normalizer and an exact production credential-loader-to-client preflight for both producer and auditor.
- Immutable successor baseline v4 later produced 474/474 ticker outcomes, 1,896 folds, and 56,880 out-of-sample rows under producer InvocationID `a1323c841529468abfb1b66078181700`; independent audit raw SHA-256 `46ea3bf6e8526f802de4d39000c8201c091fbb2cf1c2f33e5dce8381701ebaff` and final-manifest raw SHA-256 `54746936464af077886908bf818b7e0703c06685997ac501167b755470ad4a7e` passed all gates with zero unauthorized downstream outputs. Reuse still requires a fresh, immutable, SELECT-only readback bound to exact lineage; historical proof is not continuity proof.
- The preregistration runtime is committed and pushed at Git `af5cb30c8b4ed3d19a90c0151ec20b30edff4761`. It passed 69/69 focused tests in both direct-discovery and canonical package modes on Vultr; the full repository run passed 831 tests plus the two credential-bounded read-only ledger tests, with one unrelated skip and 152 subtests. It is not treated as deployed or runtime-verified until immutably deployed, observed against fresh Turso SELECT-only evidence, and independently audited.
- Trading, recommendations, orders, email, sniper activation, snapshot validation/promotion, and legacy nightly/QA automation remain outside this plan's autonomous authority.

## 4. Stable progress accounting

The eight user-facing research workstreams retain fixed denominators:

| # | Workstream | Fixed denominator | Completion evidence |
|---|---|---:|---|
| 1 | Historical dataset coverage and quality | 1 | independently audited full-universe report bound to immutable source lineage |
| 2 | Immutable Turso research dataset/version | 1 | write-once dataset manifest plus fresh Turso readback of exact identity and counts |
| 3 | Simple baselines | 1 | independently audited full-universe baseline completion |
| 4 | Variable predictive lead-lag model | 3 | implementation; governed behavioral tests; accepted governed model fit |
| 5 | Rolling windows | 4 | separately proven 30, 60, 126, and 252-session contracts/results; a statistically impossible window is resolved only by an explicitly governed alternative, never by weakening safeguards |
| 6 | Statistical evaluation | 5 | walk-forward OOS; convergence; calibration; costs/slippage; drawdown/adverse cases |
| 7 | Per-prediction evidence table | 474 | one complete, schema-valid, lineage-bound research evidence row per governed universe ticker |
| 8 | ETF posterior priors | 1 | independently audited stock-posterior-to-ETF prior artifact with cutoff and constituent lineage |

Percentages must always state `completed/total` and the exact scope. A status can regress from `VERIFIED` if evidence expires or contradicts, but a denominator cannot silently change. Production readiness is reported separately and remains `UNKNOWN` until its named acceptance checklist is adopted.

## 5. Execution topology and parallelism

The critical path is:

`S00 -> S01 -> S02 -> S03 -> S04 -> S05 -> S06 -> S07 -> S08 -> S09 -> S10 -> S11 -> S12 -> S13 -> S14 -> S15 -> S16`

Safe parallel lanes are:

- **Continuity lane:** `S02`, then one guarded nightly ingestion per completed NYSE session until `S16` retires it.
- **Research-input lane:** `S04` and `S05` may proceed after governance and incident closure.
- **Implementation lane:** fixture-only implementation and tests for `S07`, `S08`, `S10`, `S11`, `S12`, and `S13` may proceed before upstream research outputs exist, but fitting and writes remain gated.
- **Architecture lane:** read-only inventory and additive adapters in `S14` may proceed while model research runs, provided they cannot alter ingestion, snapshot lifecycle, or production data.
- **Plan/QA lane:** the three verification passes in Section 8 run after every material plan or registry change.

No two lanes may write the same Turso object, snapshot, run ID, output namespace, unit file, deployment directory, or Git path concurrently.

## 6. Stage-by-stage migration plan

The machine-readable source of the exact fields below is `CODEX_ORACLE_STAGE_REGISTRY.json`.

### S00 — Governance, authoritative inventory, and evidence ledger

**Dependencies:** none.
**Current evidence state:** `IMPLEMENTED_PARTIAL`; repository `AGENTS.md` and the Codex Oracle autonomy skill define boundaries, but the full migration evidence ledger must be freshly generated.

**Entry gates**

- Read current repository `AGENTS.md`, relevant Codex skill, Git HEAD/upstream/worktree, systemd units, deployment manifests, durable jobs, Turso schema/data, secret locations by metadata only, and existing Drive checkpoint.
- Confirm mode is research/paper, capital at risk is false, and forbidden services are inactive/disabled.

**Actions**

1. Create a stable stage/run ledger with stage ID, evidence state, artifact identities, timestamps, contradictions, owner, liveness interval, and successor decision.
2. Inventory every legacy CSV/Excel/SQLite/Streamlit path, Windows path, scheduler, service, production read/write boundary, credential reference, and data/model lineage field.
3. Freeze the stage registry hash and connect every report percentage to its fixed denominator.

**Tests and observations**

- Schema validation of every registry stage and evidence record.
- Dependency graph is acyclic; all dependency IDs resolve.
- Forbidden-action test proves the orchestrator refuses trading, recommendation/order creation, email, promotion/validation, sniper activation, and unapproved schema writes.
- Live observation records exact safety-unit load/active/enabled states.

**Independent readback:** a second reader recomputes Git/deployment hashes, re-reads systemd/Turso/Drive metadata, and verifies the ledger has no unreferenced completion claim.

**Auto-heal:** stale or contradictory evidence demotes only the affected claim, opens an incident, preserves prior evidence, and starts all independent safe inventory/tests. Missing worker identity changes `ACTIVE` to `STALLED` immediately.

**Rollback/fail-safe:** ledger writes are append-only/write-once; restore previous signed/hash-bound registry artifact without deleting incident evidence. All production writes remain disabled.

**Successor transition:** launch `S01`, safe portions of `S04`, fixture-only `S07/S08/S10/S11/S12/S13`, and read-only `S14` within capacity.

**Exit proof:** immutable inventory + evidence-ledger manifest, clean Git readback, safety-unit readback, and independent registry audit all pass.

**Avi approval:** required only to amend the operating rules, weaken safeguards, add credentials, or authorize a material external commitment.

### S01 — Close the 2026-08-26 ingestion and successor-baseline incidents

**Dependencies:** `S00`.
**Current evidence state:** ingestion false-red cause `TESTED_NOT_DEPLOYED`; baseline v1 endpoint-shape defect `DIAGNOSED_AND_SUPERSEDED`; immutable baseline v4 `VERIFIED_HISTORICAL`.

**Entry gates**

- Preserve exact failed InvocationIDs, unit definitions, commands, Git/deployment identities, journals, environment-file metadata, checkpoint/log hashes, Turso rows/counts, and timestamps.
- Confirm the recovered snapshot remains `STAGING`, unique, unpromoted, and has zero unauthorized downstream rows.

**Actions**

1. Reproduce the ingestion false-red with a sanitized fixture containing 474 feature tickers plus `^TNX`/`^VIX` lineage.
2. Replace count-equality logic with exact-set reconciliation and explicit macro membership; retain duplicate, missing, extra, wrong-date, wrong-code, wrong-status, and downstream-output failures.
3. Bind the baseline v1 endpoint-shape failure to its exact InvocationID/journal and prove the shared endpoint normalizer plus production credential-loader-to-client preflight covers producer and auditor.
4. Preserve and independently read back the v4 successor identities; add a regression test reproducing rejection of a bare HTTPS endpoint and acceptance of the normalized `/v2/pipeline` endpoint.
5. Build an explicit handoff artifact between ingestion reconciliation and baseline start; the baseline may start only after this artifact is independently verified.

**Tests and observations**

- Focused exact-set postflight tests, negative/duplicate/missing/extra/session/code/status tests, shell wrapper tests, unit-file ordering tests, and full regression suite.
- Fault injection: delayed Turso visibility, duplicate snapshot, missing macro, provider mismatch, stale checkpoint, garbage-collected transient unit, missing deployment file, and nonzero child process.
- Next guarded runtime must show deployed identity, one snapshot, exact reconciliation, durable terminal marker, and successor launch or explicit safe-stop reason.

**Independent readback:** a separate auditor queries exact snapshot metadata, feature counts/set, provider lineage set, source session, checksums, code version, approval/screening counts, and baseline handoff artifact without trusting producer stdout.

**Auto-heal:** prevent duplicate snapshot/run; if visibility is delayed, bounded read-only polling with a declared timeout; if deterministic contract failure, stop retrying, preserve evidence, repair/test/deploy, and resume the same idempotent operation. Never convert `STAGING` to another status.

**Rollback/fail-safe:** retain prior immutable deployment, disable only the failing one-time unit, restore previous unit/drop-in, and keep the snapshot quarantined as `STAGING`. Never delete or overwrite it.

**Successor transition:** after verified reconciliation, launch `S02` continuation and `S06` baseline recovery if resource gates pass. If no valid market data candidate exists, preserve the session gap and schedule the next guarded nightly extraction; do not fabricate continuity.

**Exit proof:** incident report binds both failures to exact evidence, repaired code is committed/pushed/deployed, regression tests pass, a controlled runtime or equivalent full behavioral rehearsal is observed, and independent readback reports no contradiction.

**Avi approval:** required for production schema/data change, destructive snapshot repair, new credential, validation/promotion, or weakened contract; not required for read-only diagnosis, additive reversible code, tests, or same-operation idempotent recovery.

### S02 — Temporary guarded nightly continuity

**Dependencies:** `S00`; incident hardening from `S01` must be deployed before the next runtime.
**Current evidence state:** `IMPLEMENTED_PARTIAL`; a temporary continuity concept exists, but each new unit/date must be freshly verified.

**Entry gates**

- Derive the latest completed NYSE session from the NYSE calendar and `America/New_York`; never hard-code an Israel-market relationship.
- Prove no unique snapshot already exists for the session; verify approved universe lineage, provider credentials by presence/permission only, resource headroom, immutable code/deployment identity, and safety units.

**Actions**

1. Maintain one reusable guarded timer/service pair that computes the source session, uses a session idempotency key, and writes only a `STAGING` market-input snapshot.
2. Apply strict Yahoo raw-OHLC validation and ticker-scoped Tiingo fallback; record final provider for every feature ticker and required macro source.
3. Run postflight exact reconciliation and create a write-once handoff marker for safe research successors.
4. Continue nightly until `S16` verifies final migration acceptance, then retire the temporary job.

**Tests and observations**

- Calendar/DST/holiday tests; duplicate-session/idempotency tests; fallback tests including one-cent OHLC inconsistency; checksum reconstruction tests; provider lineage tests; partial write/crash/restart tests; resource priority tests.
- Runtime must expose unit, InvocationID, PID, exact command, immutable identity, start time, checkpoint marker/age, CPU/memory, and journal.

**Independent readback:** require exactly one new STAGING snapshot, exact ticker/row/checksum/session reconciliation, complete provider lineage, and zero validation, promotion, approval, screening, recommendation, or order side effects.

**Auto-heal:** bounded transient provider retry; ticker-level failover only when strict raw validation fails; deterministic failures stop and open an incident; restart resumes with the same session/idempotency key and cannot create a duplicate. Ingestion preempts research resources.

**Rollback/fail-safe:** disable the affected timer/service, keep partial/rejected data quarantined, restore immutable prior deployment, and preserve all logs/checkpoints. Never promote or delete to hide a failure.

**Successor transition:** verified handoff starts eligible `S04`/`S05`/`S06` work; failure starts incident recovery while unrelated fixture/testing lanes continue.

**Exit proof:** at least one post-hardening guarded runtime is `OBSERVED` and independently `VERIFIED`; recurring timer state and next trigger are read back; retirement proof is deferred to `S16`.

**Avi approval:** required for new credentials, provider-contract changes that alter semantics/cost commitments, schema application, validation/promotion, or destructive cleanup.

### S03 — Claim enforcement, secrets, and change-control pipeline

**Dependencies:** `S00`.
**Current evidence state:** `IMPLEMENTED_PARTIAL`; rules exist, but every code/deployment path must be mechanically enforced.

**Entry gates:** inventory current claim rules, CI/test hooks, secret scanner, commit/push/deploy process, and signing/attestation capability.

**Actions**

1. Enforce stage vocabulary and required proof fields in reports and manifests.
2. Reject unsupported `fixed`, `healthy`, `complete`, or `verified` claims.
3. Add pre-commit/CI/deployment checks for forbidden sources, secrets, unsafe units/actions, unpinned dependencies, dirty worktrees, and absent rollback/test evidence.
4. Require immutable executor manifests and independent readback for deployed claims.

**Tests and observations:** positive and negative claim fixtures, forward tests, tamper tests, stale-evidence tests, secret canaries, forbidden-source imports, unit-state contradictions, unsigned/wrong-hash manifests, and real clean commit/push/deploy rehearsal.

**Independent readback:** separate checker recomputes hashes and stage transitions from source evidence; it must reject producer self-attestation.

**Auto-heal:** automatically demote unsupported claims, quarantine offending artifacts, prevent deploy, open a precise repair task, and continue unrelated safe work.

**Rollback/fail-safe:** remove the enforcement hook through a reviewed revert only if it itself blocks safe recovery incorrectly; default is fail closed with production actions disabled.

**Successor transition:** enforcement becomes a required gate for every remaining stage and final report.

**Exit proof:** three independent forward-test classes pass, enforcement is deployed and observed on at least one accepted and one rejected change, and the clean commit is read back from origin.

**Avi approval:** required to relax a claim/evidence rule or secret/safety gate.

### S04 — Historical stock dataset coverage and quality audit (workstream 1)

**Dependencies:** `S00`, source lineage from `S01` or an already verified immutable historical source.
**Current evidence state:** prior audit evidence indicates 1,244 sessions and the governed universe; freshness and immutable binding must be re-read.

**Entry gates:** SELECT-only Turso access; exact snapshot/universe/session/provider/schema/code identities; no CSV/SQLite fallback.

**Actions:** audit dates, NYSE sessions, ticker coverage, duplicates, nulls, OHLC invariants, non-finite values, corporate-action discontinuities, provider lineage, freshness, schema, and source/session availability cutoffs.

**Tests and observations:** pure quality-rule fixtures plus full-universe persistent audit; declare checkpoint interval and deterministic row/ticker/session totals.

**Independent readback:** independently recompute aggregate counts, exception sets, dataset hash/manifest, and cutoff evidence from Turso.

**Auto-heal:** classify repairable metadata/code defects separately from source-data defects; apply only additive/reversible code repair automatically. Data mutation, substitution, or corporate-action correction requires approval and a new version.

**Rollback/fail-safe:** no source mutation; quarantine invalid candidate versions and retain prior verified dataset.

**Successor transition:** start `S05` only for an accepted exact dataset; continue fixture-only downstream implementation if blocked.

**Exit proof:** 1/1 audit manifest is write-once, hash-bound, independently verified, and records all exceptions and residual uncertainty.

**Avi approval:** required for source-data mutation, provider-semantic change, schema change, or acceptance of an exception that weakens safeguards.

### S05 — Immutable Turso research dataset/version (workstream 2)

**Dependencies:** `S04`.
**Current evidence state:** `UNVERIFIED 0/1` for the current replacement research version.

**Entry gates:** verified historical audit; approved existing research schema and exact append-only writer scope; run authorization and idempotency key; otherwise write remains approval-required.

**Actions:** freeze snapshot ID, source session range, universe set, provider lineage, schema, row/ticker/session counts, checksums, available-at cutoffs, code/config/dependency identities, and write-once manifest.

**Tests and observations:** canonical serialization/hash tests, duplicate idempotency, partial-write rollback, mutation rejection, lineage completeness, cutoff/no-lookahead, permission scope, and persistent writer checkpoints.

**Independent readback:** SELECT-only reader reconstructs identity and exact counts/checksums from Turso and compares to the producer manifest.

**Auto-heal:** resume incomplete append-only write using the same run/idempotency key; never create a replacement ID silently. Checksum mismatch quarantines the candidate and blocks downstream work.

**Rollback/fail-safe:** candidate remains unaccepted/quarantined; consumers stay pinned to the prior verified version. Destructive cleanup is forbidden.

**Successor transition:** launch `S06` and finalize runtime preregistration inputs for `S07`.

**Exit proof:** 1/1 immutable research version is independently verified with zero contradictory rows and no unauthorized downstream outputs.

**Avi approval:** required if a schema application, broader writer permission, data repair, validation/promotion, or new external commitment is needed.

### S06 — Simple baselines and rolling-window baseline contracts (workstream 3 and part of 5)

**Dependencies:** `S05`; a prior baseline may be reused only after fresh immutable readback.
**Current evidence state:** prior 474/474, 1,896-fold, 56,880-OOS baseline is `VERIFIED_HISTORICAL`; successor launch failed and requires `S01` closure.

**Entry gates:** immutable dataset; verified run preregistration; exact fold/purge/lag contract; zero temporal overlap; resource budget; unique run ID; no downstream model/ETF outputs.

**Actions:** compute majority/persistence/regularized or other preregistered simple baselines; run governed 60, 126, and 252 windows; record the 30-window feasibility decision without weakening the minimum information contract.

**Tests and observations:** fold-boundary and purge tests, no-lookahead property tests, deterministic fixture, idempotent restart, memory/CPU limits, checkpoint monotonicity, full ticker/fold/output reconciliation.

**Independent readback:** audit exact run ID, 474 coverage, familywise hypotheses where applicable, folds, purges, lag contract, snapshot/code/config lineage, and zero unauthorized downstream outputs.

**Auto-heal:** missing artifact/environment/race repair is additive and reversible; restart same run ID from checkpoint. No qualifying result is a valid outcome and never relaxes a threshold.

**Rollback/fail-safe:** stop unit, preserve partial checkpoints and failed manifest, restore prior deployment, keep downstream fitting gated.

**Successor transition:** successful audit supplies preregistration evidence to `S07`; statistically impossible 30-window contract transitions to an explicit resolution artifact (e.g., `NOT_APPLICABLE_UNDER_FIXED_SAFEGUARD`) only if the governing specification permits it—never to fabricated completion.

**Exit proof:** workstream 3 is 1/1; each accepted window has a separate exit proof; all outputs are independently audited.

**Avi approval:** required to change model/window semantics, minimum sample safeguards, or data/schema scope; not required for exact same-run technical recovery.

### S07 — Stock-model preregistration and runtime authorization envelope

**Dependencies:** `S03`, `S05`, `S06`.
**Current evidence state:** canonical runtime commit/push and tests are `TESTED` at `af5cb30c8b4ed3d19a90c0151ec20b30edff4761`; immutable deploy/observe/verify remain pending.

**Entry gates:** fresh SELECT-only baseline readback; immutable final/audit identities; exact model code/config/dependencies; frozen hypotheses, hierarchy, lags 1–7, depth 1–5, folds, sampler, seeds, thresholds, outputs, resource limits, and side-effect prohibitions.

**Actions:** deploy the committed secret-free runtime as an immutable closure; produce current baseline readback; write preregistration exactly once; independently audit; separately create a fit-authorization artifact only when all gates pass.

**Tests and observations:** contract/binding/runtime/reader/auditor tests; malformed/tampered/stale/wrong-hash/wrong-owner/wrong-mode inputs; query allowlist; no write SQL; deployment closure/import tests; root 0600 write-once artifact tests.

**Independent readback:** separate auditor uses actual raw hashes and current Turso SELECT evidence, not caller-supplied placeholders; verifies zero side effects and `model_fit_authorized` state.

**Auto-heal:** regenerate only stale readback evidence; repair deterministic code/deployment defect with a new immutable identity; never bind to expired, wrong, or caller-invented hashes. Fitting remains off until authorization is explicit.

**Rollback/fail-safe:** retain prior deployment, revoke/ignore failed authorization artifact, stop candidate unit, and preserve manifest/audit evidence.

**Successor transition:** launch safe implementation tests in `S08`; launch fitting only when the separate authorization says true and resource gates pass.

**Exit proof:** canonical commit/push readback, immutable deployment manifest, current readback, write-once preregistration, independent audit, and explicit authorization decision are all bound.

**Avi approval:** required for a new model family/semantics, production schema, broader write scope, safeguard changes, or model-to-order use; already approved exact research fit may proceed when all preregistration gates pass.

### S08 — Variable predictive lead-lag stock model (workstream 4)

**Dependencies:** implementation can start after `S03`; governed fitting requires `S07`.
**Current evidence state:** 2/3 reported for implementation and behavioral tests; governed fit pending and must be freshly verified.

**Entry gates:** independent edges lags 1–7, depth 1–5; training-only selection; multiple-testing control; frozen hierarchy; immutable dataset; authorized run; sampler/resource/output contracts.

**Actions:** fit only the preregistered model; persist append-only checkpoints/posteriors under the approved schema and run ID; record exact convergence and sampling telemetry.

**Tests and observations:** synthetic lag-recovery tests, null/no-signal tests, hierarchy tests, training-only feature selection, lookahead/property tests, multiple-testing tests, deterministic seeds, sampler diagnostics fixtures, crash/restart/idempotency, resource bounds, and checkpoint freshness.

**Independent readback:** verify posterior count, ticker/edge/lag/depth coverage, run/snapshot/code/config/sampler lineage, timestamps/cutoffs, and absence of model-to-order or ETF-prior outputs.

**Auto-heal:** transient worker failure resumes same run/checkpoint; stale marker triggers evidence preservation and smallest repair; numerical/convergence failure is a scientific outcome, not a reason to silently change sampler/model/threshold.

**Rollback/fail-safe:** stop worker, quarantine partial posterior, retain immutable inputs/checkpoints, and prohibit downstream consumption.

**Successor transition:** independently accepted posteriors feed `S09` and `S10`; no-qualifying or failed-fit outcomes feed a separately preregistered research successor, not an ad hoc change.

**Exit proof:** workstream 4 is 3/3 only after governed fit terminal state, exact reconciliation, diagnostics, and independent audit pass.

**Avi approval:** required for any unpreregistered model/sampler/threshold/hypothesis change or use beyond research.

### S09 — Rolling-window comparison (workstream 5)

**Dependencies:** `S06`; posterior-dependent comparisons also require `S08`.
**Current evidence state:** reported 3/4 (60, 126, 252); 30 is blocked by fixed statistical safeguards.

**Entry gates:** window-specific preregistration; same immutable dataset/cutoff; minimum observations/pairs/folds; comparable metrics and costs; no silent 126-session safeguard weakening.

**Actions:** independently audit existing 60/126/252 results; determine whether 30 can meet the governed contract. If it cannot, produce a formal infeasibility proof and a specification decision rather than relabeling it complete.

**Tests and observations:** boundary/sample-size tests, fold feasibility, temporal overlap, same-universe comparability, metric schema, restart/idempotency, and runtime resource telemetry.

**Independent readback:** exact per-window run IDs, counts, folds, purges, cutoffs, metrics, lineage, and infeasibility evidence.

**Auto-heal:** technical failures resume exact window/run. Statistical infeasibility blocks only that window while all independent windows/evaluation continue.

**Rollback/fail-safe:** preserve rejected window results; no threshold/sample safeguard change without explicit governance.

**Successor transition:** accepted windows feed `S10`; unresolved 30-window decision is surfaced separately and cannot stall unrelated statistical components.

**Exit proof:** numerator is explicit: accepted results plus any formally governed resolution whose semantics were predeclared. No percentage reaches 4/4 by silently changing the denominator or standard.

**Avi approval:** required to redefine the 30-window completion semantics or weaken any minimum-sample safeguard.

### S10 — Full stock statistical evaluation (workstream 6)

**Dependencies:** test harness implementation may proceed after `S03`; runtime evaluation requires `S08` and relevant `S09` outputs.
**Current evidence state:** 3/5 harness components reported tested (calibration, costs/slippage, drawdown); walk-forward posterior evaluation and convergence pending.

**Entry gates:** accepted posteriors, frozen evaluation specification, baselines, window identities, metric thresholds, cost/slippage assumptions, and adverse scenarios.

**Actions:** run walk-forward OOS evaluation, convergence diagnostics, calibration, transaction costs/slippage, drawdown and adverse-scenario tests; compare against appropriate baselines with uncertainty.

**Tests and observations:** metric fixtures, leakage tests, confidence/credible interval checks, R-hat/ESS/divergence checks, calibration bins, cost monotonicity, drawdown reconstruction, adverse cases, missing/non-finite rejection, crash/restart, and checkpoint telemetry.

**Independent readback:** recompute all five component summaries from immutable raw outputs and verify exact model/data/config/cutoff lineage.

**Auto-heal:** retry only transient computation; deterministic metric bug gets code repair/new immutable identity; scientific failure remains failed and blocks acceptance without changing thresholds.

**Rollback/fail-safe:** quarantine failed evaluation, keep model unaccepted, and preserve all raw outputs.

**Successor transition:** accepted stock evidence feeds `S11`; failed evidence triggers separately preregistered research successor while nondependent migration work continues.

**Exit proof:** 5/5 components independently verified and the documented acceptance decision is reproducible; no profitability/causal claim exceeds evidence.

**Avi approval:** required for metric/threshold/cost assumption changes after preregistration or any promotion beyond research.

### S11 — Per-prediction evidence table (workstream 7)

**Dependencies:** schema/tests may proceed after `S03`; population requires `S08` and decision comparison requires `S10`.
**Current evidence state:** schema/policy tests reported; 0/474 populated governed predictions.

**Entry gates:** accepted governed posterior evidence, exact universe 474, frozen table schema, inherited AG decision logic captured as audited comparison only, Codex research decision policy, hard gates, and sizing policy. No order/recommendation side effect.

**Actions:** create one research evidence row per ticker containing raw Bayesian output; inherited AG eligibility and reasons; proposed Codex research decision and reasons; hard safety gates; sizing adjustments; data/model/config/cutoff identities; uncertainty and rejection reasons.

**Tests and observations:** 474-cardinality, schema, field completeness, deterministic reason codes, hard-gate precedence, no-trade missing/stale inputs, sizing bounds/non-finite rejection, lineage/cutoff, idempotency, and forbidden downstream writes.

**Independent readback:** query all 474 rows, reconstruct decisions and reason codes from raw evidence, verify unique identifiers and zero pending orders/approval events/recommendation publication.

**Auto-heal:** resume missing rows by same run/idempotency key; inconsistent row is quarantined and recomputed from immutable inputs; never fill missing posterior fields with defaults.

**Rollback/fail-safe:** candidate table/version remains research-only and unaccepted; no consumer is enabled.

**Successor transition:** only a 474/474 accepted table plus `S10` acceptance can unlock `S12`.

**Exit proof:** 474/474 rows pass independent field, decision, lineage, and side-effect audit.

**Avi approval:** required before any table is exposed as a production recommendation source, connected to approval/order flow, or used for capital sizing.

### S12 — Auditable ETF posterior priors and ETF research (workstream 8)

**Dependencies:** `S10`, `S11`.
**Current evidence state:** `DEPENDENCY_BLOCKED 0/1`, correctly gated.

**Entry gates:** stock model proven; 474/474 evidence table; ETF universe/constituents/weights/cutoffs frozen; no legacy fundamentals CSV; stock evidence available before ETF cutoff.

**Actions:** derive ETF priors/features from relevant stock posteriors and constituent whales; store contributing stock scorecard IDs, weights, source/available-at timestamps, transformation, role, and model version; evaluate dynamic replacement only under a preregistered rule.

**Tests and observations:** constituent-weight reconciliation, cutoff/no-lookahead, missing constituent, stale stock evidence, transformation determinism, prior sensitivity, dynamic-replacement boundaries, Turso-only source, crash/restart/idempotency, and zero order/recommendation writes.

**Independent readback:** reconstruct every ETF prior from stock evidence and constituent data; verify lineage, cutoff, weights, model identity, and research-only side effects.

**Auto-heal:** missing or stale stock evidence blocks the affected ETF; technical write/computation repair resumes same run. It never substitutes CSV or unproven stock evidence.

**Rollback/fail-safe:** quarantine candidate ETF artifacts and retain prior verified research version; no production consumer.

**Successor transition:** accepted ETF research evidence feeds paper/shadow acceptance in `S15`; failures trigger separately preregistered ETF research successors.

**Exit proof:** 1/1 ETF-prior artifact is independently verified and all supported ETF predictions pass walk-forward/statistical governance.

**Avi approval:** required for model/rule changes after preregistration, production schema changes, dynamic-universe production use, or recommendation/order integration.

### S13 — Turso-only production boundary and application/API migration

**Dependencies:** `S00`, `S03`; implementation can proceed in parallel with research.
**Current evidence state:** `PARTIAL_UNVERIFIED`; target is Turso + FastAPI/frontend, but legacy source paths exist and must be exhaustively mapped.

**Entry gates:** full source/deployment path swipe; exact table/API/UI contract map; approved schema already exists or approval obtained; dashboard owner and port are uniquely identified.

**Actions:** replace/remove production-path CSV/Excel/SQLite/Streamlit and Windows-local dependencies; enforce Turso repositories; align FastAPI/frontend contracts; eliminate duplicate schedulers/process ownership; keep historical files preserved until reviewed cleanup.

**Tests and observations:** static forbidden-path/import scans, repository contract tests, Turso integration on isolated/nonproduction scope, API schema tests, frontend contract tests, single-owner port/process checks, degraded-Turso fail-closed tests, and deployment rollback rehearsal.

**Independent readback:** second path scanner plus live deployment manifest, process/port owner, API health/schema, and Turso query evidence. Absence claims require full-scope searches with exclusions documented.

**Auto-heal:** code/config defects receive additive reversible repair and redeploy; Turso unavailable means read-only degraded/no-action state, never local fallback.

**Rollback/fail-safe:** atomic deployment switch to prior immutable version; dashboard remains read-only; no database mutation or duplicate Uvicorn owner.

**Successor transition:** verified service/data boundary feeds `S15`; reviewed legacy inventory feeds `S16` retirement.

**Exit proof:** no production execution path can read/write CSV, Excel, SQLite, or Streamlit; API/frontend behavior and single service ownership are independently verified.

**Avi approval:** required for production schema, destructive legacy removal, service behavior changes affecting execution/risk/model semantics, or new credentials.

### S14 — Operational resilience, observability, and autonomous recovery

**Dependencies:** `S01`, `S02`, `S03`; integrates with every long-running stage.
**Current evidence state:** `PARTIAL`; individual units/checkpoints exist, but the complete failure matrix must be proven.

**Entry gates:** catalog every worker, timer, lock, idempotency key, checkpoint, retry class, maximum interval, resource limit, and dependent successor.

**Actions:** standardize persistent systemd templates, durable JSON checkpoints, invocation/run IDs, liveness watchdogs, resource admission, ingestion priority, bounded retry classes, successor dispatcher, incident artifacts, and read-only monitors.

**Tests and observations:** kill -9/restart, reboot-survival rehearsal where authorized in a nonproduction context, stale checkpoint, missing PID, hung CPU, OOM/resource denial, network/Turso timeout, provider failure, duplicate launch, partial write, corrupt artifact, clock/DST, and garbage-collected transient-unit tests.

**Independent readback:** monitor proves actual unit/PID/command/deploy identity/checkpoint age/resource use and separately verifies Turso progress. Producer logs alone are insufficient.

**Auto-heal:** exact decision table: transient -> bounded retry; deterministic -> preserve/repair/test/resume; scientific no-output -> preserve/transition; dependency block -> start independent safe successors; approval boundary -> stop only that edge and request one precise approval.

**Rollback/fail-safe:** stop/disable only affected unit, maintain locks, restore immutable deployment, preserve checkpoints, and keep all production/trading actions disabled.

**Successor transition:** the dispatcher must demonstrate automatic launch of at least one safe successor after injected `FAILED`, `STALLED`, `BLOCKED`, and `NO_QUALIFYING_OUTPUT` cases.

**Exit proof:** full failure-injection matrix passes and an independent monitor confirms no duplicate writes or unsafe action.

**Avi approval:** required for reboot/OS changes, destructive actions, new credentials, schema/data changes, or weakened recovery gates.

### S15 — Integrated paper/shadow readiness and end-to-end rehearsal

**Dependencies:** `S10`, `S11`, `S12`, `S13`, `S14`.
**Current evidence state:** `NOT_STARTED`.

**Entry gates:** all research artifacts accepted; Turso-only production boundary verified; no live broker integration; kill switch and hard risk gates implemented/tested; exact source session and market calendar.

**Actions:** run a research/paper-only end-to-end rehearsal from verified STAGING/research inputs through scorecards/evidence tables to a quarantined paper plan, without publishing recommendations, creating production orders, emailing, or enabling sniper.

**Tests and observations:** end-to-end lineage, calendar/session/DST, stale/missing input no-action, risk limits, kill switch, idempotent plan, reconciliation, rollback, API/UI read-only presentation, and capital-at-risk false assertion.

**Independent readback:** Turso shows only authorized paper/shadow artifacts in the exact namespace; zero live orders, approvals, emails, or sniper consumption; every output is reproducible.

**Auto-heal:** technical failures resume by same rehearsal ID; any risk/lineage/reconciliation contradiction stops downstream action and opens an incident while preserving evidence.

**Rollback/fail-safe:** disable rehearsal consumers, quarantine candidate paper artifacts, retain kill switch, restore prior deployment, and keep execution off.

**Successor transition:** verified rehearsal feeds final acceptance `S16`. Live trading is not an automatic successor and requires a separate approved governance program.

**Exit proof:** signed/hash-bound rehearsal report covers every boundary and independent readback proves capital was never at risk.

**Avi approval:** required before creating actual production recommendations/pending orders, activating sniper, connecting a broker, or any live phase.

### S16 — Final acceptance, temporary-job cancellation, and legacy retirement

**Dependencies:** all prior stages.
**Current evidence state:** `NOT_STARTED`.

**Entry gates:** every required stage exit proof is current; contradiction register empty for critical items; Git/deploy/Turso/Drive evidence synchronized; rollback packages retained.

**Actions:** run the final requirement-by-requirement audit; freeze canonical architecture/runbooks; verify monitoring and incident ownership; disable/remove temporary nightly continuity schedule; disable and mask retired legacy units; archive legacy files only through an approved manifest; update canonical Drive checkpoint.

**Tests and observations:** full regression and integration suites, three plan-verification passes, clean secret/forbidden-source scans, Turso schema/data/readback, API/UI smoke, unit/timer/process/port inventory, restart/idempotency/failover rehearsal, and no unauthorized side effects.

**Independent readback:** origin commit, immutable deployment hashes, Drive metadata/content, Turso identities/counts, all systemd load/active/enabled states, exact next timers (none for retired temporary/legacy units), and artifact archive manifest.

**Auto-heal:** any contradiction reopens its owning stage and keeps temporary continuity in place if still safe; cancellation occurs only after final acceptance is verified.

**Rollback/fail-safe:** restore temporary continuity only from its last immutable verified package if migration acceptance is later revoked; never re-enable legacy AG nightly/QA/sniper automatically.

**Successor transition:** ongoing Codex Oracle operations; any live-trading program is a separately approved plan.

**Exit proof:** final acceptance manifest has all 17 stage proofs, no unresolved critical contradiction, temporary continuity is absent/disabled, legacy AG units are absent/disabled/masked as specified, GitHub and Drive readbacks match, and the goal completion audit passes.

**Avi approval:** required for destructive legacy deletion/archive, changes to final production schema/service semantics, and any transition beyond paper/shadow.

## 7. Universal test and auto-fix protocol

Every stage executes this exact loop:

1. **Preflight:** re-read authority, Git, deployment, units/processes, locks, resource headroom, durable checkpoints, Turso state, secrets metadata, and side-effect counters.
2. **Freeze:** write a run envelope containing exact inputs, hashes, code/config/dependencies, command, outputs, liveness interval, idempotency key, safety assertions, and rollback target.
3. **Focused tests:** reproduce the intended behavior and the exact historical defect.
4. **Negative/property tests:** wrong identity, stale evidence, duplicates, missing/extra rows, time leakage, non-finite values, malformed artifacts, unauthorized side effects, and resource failure.
5. **Regression tests:** run the affected package and repository suites; document counts and skips with reasons.
6. **Static and secret scans:** prohibited sources/actions, path ownership, embedded secrets, unsafe SQL, unpinned imports/dependencies, and logging exposure.
7. **Deploy atomically:** immutable versioned directory, executor manifest, restrictive ownership/mode, atomic pointer or unit drop-in, daemon reload, and deployment readback.
8. **Observe:** persistent worker identity, live PID, exact command, immutable version, checkpoint marker/age, CPU/memory/I/O, journal, and declared maximum interval.
9. **Independent verify:** different reader/auditor reconstructs exact outputs and lineage from immutable files/Turso; producer success text is ignored.
10. **Fault inject:** exercise the stage's declared failure matrix in fixtures or an isolated runtime; production destructive injection is never implicit.
11. **Classify failure:** transient, deterministic technical, scientific/no-output, dependency, approval boundary, or contradiction.
12. **Heal safely:** preserve evidence; prevent duplicate; make smallest reversible repair; rerun focused/negative/regression/static tests; create new immutable identity; resume same operation if gates still pass.
13. **Rollback:** on failed deploy/observation/verification, stop candidate, restore prior immutable version, retain quarantine evidence, and keep downstream disabled.
14. **Transition:** start every independent `SAFE_NOW` successor; attach long work to persistent units; report `NOT RUNNING` if no worker exists.
15. **Record:** append evidence state, exact counts/hashes/timestamps, remaining unknowns, and action needed from Avi.

## 8. Triple verification of this plan

The plan and JSON registry are not accepted until three distinct passes succeed:

### Pass A — Structural and referential verification

- JSON parses and matches the required registry shape.
- Every stage includes dependencies, current evidence state, entry gates, actions, tests, runtime observations, independent readback, auto-heal, rollback/fail-safe, successor transition, exit proof, and Avi-approval boundary.
- Stage IDs are unique, all dependencies/successors resolve, and the dependency graph is acyclic.
- All eight fixed-denominator workstreams map to at least one stage.

### Pass B — Safety and incident fault-model verification

- Search for prohibited production fallbacks/actions and confirm every mention is a prohibition, negative test, or explicit approval boundary.
- Scenario-walk the 2026-08-26 false-red, baseline 2.3-second failure, delayed Turso visibility, duplicate run, stale checkpoint, wrong checksum, provider fallback, no qualifying model output, and ingestion/research resource contention.
- Each scenario must preserve evidence, stop duplicate/deterministic retry, retain hard gates, start independent safe successors, and name rollback.

### Pass C — Independent completeness and execution-readiness verification

- A separate reviewer cross-checks Markdown against the JSON registry and repository rules.
- Every exit proof is independently observable and cannot be satisfied by shell exit alone.
- Every approval boundary is precise; safe in-scope recovery does not wait for Avi.
- The final acceptance stage proves nightly cancellation and legacy retirement only after all prerequisites.

Any failed verification modifies both artifacts, restarts all three passes, and records the new plan hash. The canonical repo/Drive copy may be updated only after all three passes are green.

## 9. Reporting contract

Every checkpoint must state:

- timestamp in Israel and UTC;
- overall conclusion in one factual sentence;
- the eight workstreams with fixed numerator/denominator or `UNKNOWN`;
- evidence maturity separately from percentage;
- Vultr Git HEAD/upstream/worktree and immutable deployment identity;
- exact tests/counts/skips;
- active workers with unit, InvocationID, PID, command, start, progress/total, checkpoint age, and resources—or `NOT RUNNING`;
- guarded nightly state, source session, snapshot identity/status, reconciliation, and successor state;
- data recovery/provider-fallback and governance maturity;
- safety service states and capital-at-risk status;
- auto-heal actions and all `SAFE_NOW` successors launched;
- one precise Avi action or `None`.

ETAs are reported only from timestamped completed/total checkpoints plus measured recent throughput. Otherwise ETA is `UNKNOWN`.

## 10. Immediate execution order from the current evidence snapshot

1. Finish `S01`: bind exact ingestion and successor-baseline failures to their journals/deployment/Turso evidence; merge, test, deploy, and independently observe the postflight/handoff repair.
2. In parallel, finish `S03` claim enforcement and deploy/test the committed `S07` preregistration runtime from `af5cb30c8b4ed3d19a90c0151ec20b30edff4761`; these do not require model fitting or snapshot promotion.
3. Keep `S02` armed for the next completed NYSE session with ingestion resource priority and exact idempotency.
4. Re-read `S04`/`S05` Turso evidence; do not infer that the new research version exists from the STAGING market snapshot.
5. Recover `S06` only after the handoff and immutable-input gates pass; use the same run ID/checkpoint and no duplicate unit.
6. Launch `S08` governed fitting only after `S07` produces an explicit fit authorization; meanwhile complete fixture/property/failure tests for `S08`–`S13` in parallel.
7. Advance `S10`, `S11`, then `S12` strictly from accepted posterior evidence.
8. Continue `S13` and `S14` in parallel, protecting ingestion resources.
9. Run `S15`, then `S16`; cancel temporary nightly continuity only at final verified acceptance.
