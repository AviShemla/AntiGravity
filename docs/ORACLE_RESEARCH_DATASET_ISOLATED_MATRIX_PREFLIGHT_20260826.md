# Oracle research dataset isolated matrix preflight — 2026-08-26

Stage: **EXTERNAL MATRIX OBSERVED / VERIFIED; PRODUCTION NOT APPLIED**

This document began as the read-only preflight. The approved disposable-branch
matrix later ran under executor commit
`64e7bc78fd0612591d7dc8ddd6fa8d8dc255d7bf`. Durable sanitized evidence is
preserved at:

- `docs/evidence/oracle_research_isolated_matrix_checkpoint_20260826.json`;
- `docs/evidence/oracle_research_isolated_matrix_readback_20260826.json`; and
- `docs/evidence/oracle_research_isolated_matrix_terminal_20260826.json`.

The run proved all 26 migration statements, all 26 expected schema objects, and
all 26 behavioral assertions on disposable branch
`theoracle-codex-oracle-rd-20260826t2009z-64e7bc`. It recorded exactly one
APPLY and one logical ROLLBACK event, zero failed-DDL/fixture residue, unchanged
production fingerprint and zero production Oracle research objects. Cleanup
was independently read back as exact branch absence. The transient systemd
unit was collected after successful completion; the durable checkpoint and
evidence hashes, not a retained unit, are the continuing proof.

This clears only the isolated-matrix evidence gate. It grants no production
schema application or dataset-freeze authority.

## Earlier orphaned branch cleanup — separate from the successful matrix

A prior lifecycle attempt created disposable branch
`theoracle-codex-oracle-rd-20260826t1945z-d530dc` (ID
`01a03f9c-2f01-74bb-8ba2-6b73aaf7b208`) but did not reach the matrix
execution stage. It is not the successful 26/26 matrix branch documented
above and supplies no migration or behavioral-assertion evidence.

The exact orphan identity was later rebound to its original intent and
terminal evidence and cleaned by immutable recovery commit
`76f96e40bea974816ceac53a4da4fe34c45caf41`. Runtime unit
`codex-oracle-unbound-cleanup-20260826t2100z-76f96e4.service`, InvocationID
`93d188dde279449a90c407a8b3ef482e`, worker PID `930140`, completed
successfully in 4.689 seconds. Sanitized evidence is preserved at:

- `docs/evidence/oracle_research_orphan_branch_pre_cleanup_20260826.json`
  (SHA-256 `0a275e15eaca8e22458e92adc5fcab3de7077c1fc8473b86077fed6afcd3ddc9`);
- `docs/evidence/oracle_research_orphan_branch_cleanup_final_20260826.json`
  (SHA-256 `c874a500ad5874cd5888728777201b5bfcb5b4c3479b98e51b69614594ae6962`).

The final evidence independently records exact branch-show not-found, exact
parent-list name absence, unchanged production fingerprint
`95cf13e3061f8fcbad798d77d96570de9293e3db8a865a0d73be918c6a5f1523`,
and zero production Oracle research objects. This cleanup exhausted only the
already-approved exact disposable-branch cleanup action. It creates no new
branch, schema, dataset-freeze, model, ETF-prior, recommendation, order, or
trading authority.

## Fresh host and production readback

- Reviewed source Git: `cf8345c30e2c8264cbb7140bef3b397a7799e488`, clean at the
  two-phase governance repair preflight.
- Turso CLI: `/home/codexops/.turso/turso`, version `v1.0.32`; it is not on the
  default PATH.
- CLI settings: `/home/codexops/.config/turso/settings.json`, mode `600`;
  authenticated owner is `avishe`. No token value was read or printed.
- Production parent: `theoracle`, database ID
  `019f09f6-0701-72e9-aad2-c64996ae63e1`, group `default`, region
  `aws-eu-west-1`.
- Required production source tables exist: `model_input_snapshots`,
  `market_daily_features`, and `market_data_provider_lineage`.
- `schema_migration_events_v2` exists with the APPLY/ROLLBACK and artifact-hash
  contract required by the approved atomic runner.
- Oracle migration APPLY-event count is `0`.
- Oracle research dataset tables are absent from production.
- Exact migration: ID
  `20260826_oracle_research_dataset_versions_additive`, schema version `1`, 26
  statements, SHA-256
  `d21aa91b356666c6509e234a74f3041130fc1e4ae62455086aa86b2b18e6e01e`.
- Atomic runner SHA-256:
  `2a43530c84d7eabd850702f6b053bd938593787ee3b40ac2eee0b6a81acd903f`.

## Harness boundary

`scripts/oracle_research_dataset_isolated_matrix.py` contains no network,
credential, branch, or database adapter. It:

- creates a hash-pinned `PreBranchIntent` before a branch ID exists, authorizing
  only the exact create/show/one-day-token vectors for one governed name;
- binds the actual distinct branch ID and parent readback into the full matrix
  plan without changing the intent's name, approval, timestamp, artifact, or
  source-commit scope;
- rejects a branch name/ID that aliases production;
- requires the exact parent name/ID and governed branch-name pattern;
- requires explicit lifecycle approval for branch creation, one-day credential,
  isolated schema application, fixture writes, logical rollback, and cleanup;
- reparses and hashes the migration and requires exactly 26 statements;
- emits immutable argument vectors rather than shell command strings;
- marks token output as sensitive and branch destruction as destructive;
- defines 26 behavioral assertions covering additive application, staging,
  freeze/revoke ordering, duplicate prevention, frozen evidence/source guards,
  injected DDL rollback, and ambiguous-commit readback; and
- accepts execution only through an injected non-production adapter, then fails
  closed on any missing assertion, object, event, rollback, residue, identity,
  or unchanged-production proof.

The preflight-only CLI prints either a redacted `PRE_BRANCH_INTENT` or a bound
full JSON plan, always with `no_changes=true`. It has no execute flag.

## Two-phase governed invocation

Phase A must be preserved before creation. Choose the governed name once; do
not regenerate it after a failed or ambiguous create response.

```text
/opt/antigravity/venv/bin/python scripts/oracle_research_dataset_isolated_matrix.py \
  --branch-name <governed-branch-name> \
  --approval-id <six-action-approval-id> \
  --source-commit cf8345c30e2c8264cbb7140bef3b397a7799e488
```

The resulting `PRE_BRANCH_INTENT` must pin its `intent_id`, canonical
`created_at_utc`, approval ID, branch and production-parent identity, exact
migration identity, and only these three command purposes: `create_branch`,
`read_branch_identity`, and `create_one_day_branch_token`. Preserve the
redacted JSON before running its create vector.

After `db show` returns the distinct branch ID and exact production-parent
readback, bind that identity using the preserved intent timestamp:

```text
/opt/antigravity/venv/bin/python scripts/oracle_research_dataset_isolated_matrix.py \
  --branch-name <same-governed-branch-name> \
  --branch-id <actual-distinct-branch-id> \
  --parent-name theoracle \
  --parent-id 019f09f6-0701-72e9-aad2-c64996ae63e1 \
  --intent-id <preserved-intent_id> \
  --intent-created-at-utc <preserved-created_at_utc> \
  --approval-id <same-six-action-approval-id> \
  --source-commit cf8345c30e2c8264cbb7140bef3b397a7799e488
```

The intent ID hashes the approval, branch and parent identity, timestamp,
source commit, and complete migration identity. Any name, parent, approval,
timestamp, source commit, migration, or intent-ID drift blocks binding. The
second output is still a no-change plan, not execution authority or an
executor.

## Governed branch identity

Required name:

```text
theoracle-codex-oracle-rd-20260826tHHMMz-<6 lowercase hex>
```

The branch readback must identify parent `theoracle`, parent ID
`019f09f6-0701-72e9-aad2-c64996ae63e1`, and a distinct branch ID. A name alone
is not identity proof.

## Historical governed command plan — executed by the lifecycle worker

These vectors remain the reviewed historical plan. They are documentation, not
fresh authority and must not be replayed.

1. Create from the production parent:

   ```text
   /home/codexops/.turso/turso db branch theoracle <governed-branch-name>
   ```

2. Read branch identity and record its distinct database ID:

   ```text
   /home/codexops/.turso/turso db show <governed-branch-name>
   ```

3. Create a one-day branch credential:

   ```text
   /home/codexops/.turso/turso db tokens create <governed-branch-name> --expiration 1d
   ```

   This command emits a secret. Its stdout must go directly to a mode-600
   temporary credential file and must never enter terminal capture, chat, Git,
   reports, or durable logs.

4. Run the atomic runner in check-only mode first:

   ```text
   /opt/antigravity/venv/bin/python scripts/apply_atomic_migration.py migrations/20260826_oracle_research_dataset_versions_additive.sql
   ```

5. Only after branch URL/token variables resolve to the approved branch, invoke
   the exact `--apply --expected-sha256 ... --target-environment isolated`
   vector emitted by the harness. The evidence JSON binds approval ID, branch
   name, parent ID, and isolated-matrix scope. Never print the environment.

6. Execute the 26 behavioral assertions through a reviewed adapter in one
   bounded fixture transaction, deliberately roll fixture writes back, append
   the separate logical ROLLBACK ledger event, and independently read back zero
   fixture/failed-DDL residue.

7. Preserve and commit the redacted evidence package before resource cleanup.

8. After separately confirming cleanup authority:

   ```text
   /home/codexops/.turso/turso db destroy <governed-branch-name> --yes
   ```

9. Independently prove the branch is absent and production fingerprints/object
   counts are unchanged.

## Rollback and retry boundary

- Failure before branch creation: stop; nothing exists.
- Failure after creation but before schema commit: preserve identity/logs,
  revoke/discard the temporary credential, then destroy only the exact approved
  branch after evidence capture.
- Failure before atomic migration COMMIT: require verified transaction ROLLBACK
  and absence of both objects and APPLY event.
- Failure or ambiguity after COMMIT: do not retry. Perform read-only exact
  object/ledger readback; append logical ROLLBACK only if the approved matrix
  scope permits it.
- Behavioral fixtures run transactionally and must leave zero residue.
- Branch destruction is resource cleanup, not evidence rollback. Preserve the
  schema, APPLY/ROLLBACK events, raw redacted readbacks, hashes, and production
  comparison before destruction.
- Never destroy by glob, unresolved variable, parent name, or production ID.

## Approval sufficiency

The completed lifecycle is bound to approval ID
`avi-six-action-matrix-20260826`, exact pre-branch intent
`oracle-rd-pre-branch-intent-5f944805607361f7`, the six governed actions, and
the exact disposable branch identity. That approval is exhausted for this
completed lifecycle and is not reusable authority for production application,
dataset freezing, a new branch, or a replay.
