# Oracle research dataset production application and freeze runbook

Status: **REVIEW-ONLY / NOT EXECUTABLE**
Reviewed artifact baseline: `eb08ce518a557bf6b772aa66e6bad25e3d681cd3`
Isolated-matrix executor commit: `64e7bc78fd0612591d7dc8ddd6fa8d8dc255d7bf`
Machine-readable contract:
`governance/oracle_research_dataset_application_contract.json`
Contract SHA-256:
`06febf827d933afa26437db72291d25dacec432826ffa35d727c88c7dfa1dfbb`

This runbook grants no production authority. It separates two operations that
must never share an implied approval:

1. applying the additive research-dataset schema; and
2. staging and freezing one exact research dataset version.

Schema approval does not authorize a dataset freeze. Freeze approval does not
authorize schema application. Each approval must identify its own scope,
artifact hashes, target database, actor, expiry, and rollback boundary. The two
approval IDs must be distinct.

## Current hard blockers

Both production operations are fail-closed today. The additive schema artifact
is syntactically compatible with the approved atomic runner and its exact
disposable Turso matrix is now independently recorded. Neither fact is
production application authority.

- The marker-compatible migration hash is
  `d21aa91b356666c6509e234a74f3041130fc1e4ae62455086aa86b2b18e6e01e`;
  it contains migration ID
  `20260826_oracle_research_dataset_versions_additive`, schema version `1`, and
  exactly 26 named additive statements.
- No production schema approval exists.
- The exact hash-pinned isolated Turso application/failure matrix is attached
  to this contract through three sanitized evidence artifacts. It proved 26/26
  statements, 26/26 schema objects, 26/26 behavioral assertions, one APPLY and
  one logical ROLLBACK event, zero fixture/failed-DDL residue, unchanged
  production fingerprint, zero production Oracle objects, and exact branch
  cleanup readback. This clears only the matrix evidence gate.
- `oracle_research_dataset_writer.py` is an implemented, tested pure transaction
  interface at SHA-256
  `0220845dcb870946e38c08055d1ea0a663be8e5cc2232b57b8b237f2eb065adf`.
  It owns no connection, credentials, or transport.
- `oracle_research_dataset_serializers.py` is an implemented, tested streaming
  serializer interface at SHA-256
  `c4b7621663de01dc5a4a56abe73992ae89f9502612e614b7200c13ed3239eac7`.
  It defines versioned canonical content and ticker-universe encodings without
  materializing the full snapshot.
- `oracle_research_dataset_content_reader.py` is an implemented, tested
  read-only interface at SHA-256
  `caf92cd75c7399648b9716b7c5ceba30171856ad243d48275fcb1e93e2b1118c`.
  It performs bounded keyset `SELECT`-only streaming into the canonical
  digester and reports zero retained rows; it owns no endpoint, credentials,
  connection, or production write path.
- `oracle_research_dataset_freeze_manifest.py` is an implemented, tested
  `REVIEW_ONLY` immutable-manifest builder at SHA-256
  `6bca13f27fd30e76dd64f393c9647633baceb5e83d592f95e1aa8ed04c46420f`.
  It cannot build a production manifest without two distinct real schema and
  freeze approval IDs. Neither approval exists, so no actual production
  manifest has been built.
- `oracle_research_dataset_turso_adapter.py` is an implemented, tested injected
  atomic interface at SHA-256
  `316c13aa221b6c3af3f2b6488f06c82d85b4991d61c4b9b24bc7820e0af504db`.
  It owns no endpoint, token, session, or environment lookup, has never been
  used in production, and is not approved for execution.
- The migration has not been approved or applied.
- The actual 586,710-row production content/ticker digest is
  `OBSERVED/VERIFIED_READBACK` in the sanitized canonical evidence record
  `docs/evidence/oracle_research_content_audit_20260826.json`. The SELECT-only
  unit retained zero rows; its independently recomputed logical evidence hash
  is `b0b775d6aa4ff37faacb3987a65019724b358cdc86d5aa5967aea927c1401df3`.
  This clears only the content-digest readback blocker and grants no schema or
  freeze authority.
- No production dataset freeze or freeze readback has been performed.
- No separately scoped dataset-freeze approval exists.

Clearing one blocker never clears another. Any later correction is a new
reviewed artifact with a new SHA-256; it may not silently replace the hash
above or reuse its approval.

## Locked artifacts

The machine-readable contract pins the migration, frozen-dataset read-only
reader, bounded source-content read-only streaming interface, canonical
streaming serializers, review-only freeze-manifest builder, pure freeze-writer
interface, injected atomic Turso adapter, atomic migration runner, source commit,
and target Turso database identity. Before any approved
operation, independently hash the bytes on the execution host and compare every
value with the contract. Any mismatch stops the operation and creates an
incident record; do not regenerate hashes during the same approval.

The freeze manifest must additionally pin:

- dataset version ID and market snapshot ID;
- market snapshot checksum and source session;
- evidence cutoff and first/last session;
- expected row, ticker, session, and provider-lineage counts;
- independently computed content, ticker-universe, and provider-lineage hashes;
- schema/code version, writer hash, actor, seed policy if applicable; and
- the separately granted freeze approval ID.

Placeholder bindings such as `EXPECTED_MARKET_SNAPSHOT_ID` in the audit
contract are not executable values. They must be replaced from one signed,
hash-locked freeze manifest before approval; interactive substitution is
forbidden.

## Phase A — read-only schema pre-audit

Authority: no mutation approval required; use read-only credentials.

1. Re-read canonical Git HEAD, origin, worktree cleanliness, migration bytes,
   contract bytes, runner bytes, and their SHA-256 values.
2. Confirm the target is exactly the approved Turso database and the credential
   cannot access another database.
3. Execute only the contract's `pre_schema` SELECT statements.
4. Preserve raw results, timestamp, target identity, query IDs, bindings, and a
   canonical result digest outside the repository worktree.
5. If an exact prior APPLY event exists, do not apply again. Change the task to
   readback/reconciliation. If an object exists with a different definition,
   stop as a schema collision.

Passing this audit proves only preconditions. It does not approve application.

## Phase B — additive schema application

Required authority: explicit **schema-application approval** only.

The exact statement-marked bundle is pinned in the contract and has passed the
isolated Turso matrix under the exact atomic runner. This phase remains blocked
solely at its explicit production schema-approval gate. A future separately
approved action must use one `BEGIN IMMEDIATE` transaction containing all
additive DDL and one append-only schema APPLY event, verify every response, and
commit only after all responses are `ok`. A failure before commit must issue
and verify `ROLLBACK`.

Duplicate prevention is mandatory:

- stable migration ID plus exact artifact SHA-256;
- stable event ID and exact target database ID;
- one transaction and one writer;
- no automatic retry after a lost or ambiguous commit response; and
- readback before deciding whether another action is permissible.

Do not insert a dataset version, provider binding, or freeze event in this
phase.

## Phase C — read-only schema post-audit

Authority: read-only.

1. Execute only the contract's `post_schema` SELECT statements.
2. Recompute a canonical digest of the returned object definitions and compare
   it with the reviewed isolated result.
3. Require exactly one APPLY ledger event with the approved target and artifact
   hash.
4. Require zero dataset versions, zero dataset provider rows, and zero dataset
   events. Any non-zero count proves that schema and freeze scopes were mixed.
5. Record the terminal transaction result and independent readback before the
   schema operation can advance beyond `DEPLOYED`.

The schema post-audit does not authorize freezing.

## Phase D — freeze pre-audit and safety interlock

Required authority for audit: read-only. Required authority for later mutation:
separate **dataset-freeze approval**.

No production freeze manifest currently exists. Before any freeze transaction:

1. Require two distinct real approval IDs, build the deterministic manifest,
   and then re-read the exact contract and approved freeze-manifest hashes.
2. Run only `pre_freeze` SELECT statements and bind every placeholder from the
   immutable manifest.
3. Reconcile exact source snapshot identity, checksum, source session, row/
   ticker/session boundaries, provider rows, and per-symbol checksums.
4. Reconcile the recorded `OBSERVED/VERIFIED_READBACK` evidence for exactly
   586,710 ordered rows streamed through the hash-pinned bounded keyset
   `SELECT`-only content reader and canonical serializers with zero retained
   rows. Its content SHA-256 is
   `07735e093c39546276082eba82f53a52d43a71cb1cff2d032b58f1315857a834`
   and ticker-universe SHA-256 is
   `267cdd0dba60a55346ba6f8a6e843259eacae924c9ea8740a093ea2cce3d1e26`.
   This satisfies only the production content/ticker digest readback; provider-
   lineage reconciliation and every other freeze gate remain independent.
5. Require no existing dataset version ID, frozen identity, or freeze event.
6. Confirm `FROZEN/RESEARCH` mode; keep `ag-sniper.service`,
   `antigravity-nightly.timer`, and `antigravity-qa-watchdog.timer` inactive and
   disabled; require the guarded ingestion service inactive; and prove no
   ingestion writer, model fit, snapshot promotion, recommendation/order
   staging, trading, email, or second schema/freeze writer is active.
7. Preserve the safety readback with unit/PID, InvocationID where applicable,
   exact command, start time, and observation timestamp.

Any stale, missing, ambiguous, non-finite, mismatched, or duplicate evidence is
a no-freeze condition. Never edit source market rows or thresholds to make the
manifest reconcile.

## Phase E — atomic dataset freeze

Required authority: explicit **dataset-freeze approval** whose ID differs from
the schema approval ID.

The review-only manifest builder, pure writer, bounded read-only content reader,
canonical serializer, and injected atomic adapter interfaces are implemented,
hash-pinned, and tested. The actual 586,710-row content/ticker digest has an
independently matched readback. No production manifest has been built and the
adapter has never been used. This phase remains non-executable until the adapter
is separately approved for execution; two distinct real schema/freeze approvals
exist and bind a newly built production manifest; the migration is approved and
applied; and the schema post-audit is recorded. The required transaction
contract is:

1. `BEGIN IMMEDIATE` once and acquire the single freeze-writer identity.
2. Re-run duplicate checks inside the transaction.
3. Insert one `STAGING` version carrying the exact manifest.
4. Insert exactly one provider binding for every reconciled ticker.
5. Recompute and compare all counts and hashes inside the transaction.
6. Insert exactly one append-only `FREEZE` event carrying the same hashes and
   freeze approval ID.
7. Transition only that version from `STAGING` to `FROZEN`.
8. Require every response to be `ok`; commit once. On any earlier failure,
   rollback the whole transaction and prove no partial artifact remains.

No recommendation, order, snapshot validation/promotion, model fit, service
activation, email, or trading action belongs to this transaction.

## Phase F — independent freeze post-audit

Authority: read-only and independent from the freeze writer.

1. Execute only the contract's `post_freeze` SELECT statements.
2. Call the hash-pinned read-only dataset interface with every expected identity
   from the freeze manifest.
3. Independently recompute and compare source counts, boundaries, content,
   ticker-universe, and provider-lineage hashes.
4. Require one FROZEN version, exact provider bindings, exactly one FREEZE event,
   and no REVOKE event.
5. Re-read source market metadata, rows, and provider lineage to prove they were
   not changed to obtain the freeze.
6. Preserve raw responses and canonical digests with fresh timestamps.

A committed transaction without this independent readback is at most
`DEPLOYED`, not `OBSERVED` or `VERIFIED`.

## Exact rollback and incident boundaries

- **Before schema transaction begins:** abandon the plan; production state is
  unchanged.
- **After schema begin but before commit:** verify transaction rollback and
  prove no schema object or APPLY event remains.
- **After schema commit but before freeze:** logically disable the new reader/
  writer path. Preserve every schema object and APPLY event. Never drop tables,
  triggers, indexes, or ledger evidence.
- **After freeze begin but before commit:** rollback the whole freeze transaction
  and prove no partial version, provider binding, or FREEZE event remains.
  Source market evidence remains untouched.
- **After freeze commit:** there is no destructive rollback. Disable consumers,
  preserve all frozen/source evidence, and only under a new explicit approval
  append one REVOKE event. Never mutate or delete the frozen version, provider
  binding, source snapshot, source rows, source lineage, or event history.
- **Ambiguous commit or failed rollback readback:** stop all related writers,
  preserve logs and request/response metadata without secrets, and perform only
  read-only reconciliation. Never retry blindly.

`DROP`, `DELETE`, `TRUNCATE`, evidence-rewriting `UPDATE`, snapshot promotion,
and source-row repair are outside this rollback authority. A schema correction
is a new additive, hash-pinned migration with its own approval and evidence.

## Evidence package

Each phase must preserve: contract and manifest hashes, source Git identity,
execution-host identity, target database identity, approval ID and scope, actor,
timestamps, exact query IDs/bindings, raw redacted responses, canonical result
digests, transaction outcome, independent readback, safety-unit evidence, and
all contradictions. Never store credentials, bearer headers, or response bodies
that may expose secrets.
