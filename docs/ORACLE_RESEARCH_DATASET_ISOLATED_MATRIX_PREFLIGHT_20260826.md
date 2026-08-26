# Oracle research dataset isolated matrix preflight — 2026-08-26

Stage: **IMPLEMENTED / TESTED LOCALLY; EXTERNAL MATRIX NOT RUN**

This evidence is read-only. No branch, token, schema object, fixture, rollback
event, or cleanup action was created.

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

## Required external commands — not executed

These vectors reflect CLI `v1.0.32` help and are documentation, not authority.

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

Technical platform authority is sufficient for this disposable-branch flow.
However, the repository evidence independently proves only the earlier
lag-edge-v2 branch approval. That artifact-specific approval cannot be presumed
to authorize this Oracle migration. The current harness requires one recorded
approval ID explicitly covering all six lifecycle actions above. If Avi's
earlier temporary-branch approval explicitly named this Oracle successor scope,
it is technically sufficient; otherwise a precise scope confirmation remains
required. No external action was taken.
