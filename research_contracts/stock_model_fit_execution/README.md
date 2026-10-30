# S08 governed stock model-fit execution contract

This isolated package closes the missing boundary between the verified S07
preregistration and any future S08 model process. It is pure and fixture-tested:
it does **not** contact Turso, write a database, deploy, start a service, or fit a
model.

The contract requires all of the following at the same time:

- the exact S07 preregistration remains fixture-only, non-authorizing, not
  started, freshly independently audited, and freshly read back with SELECT-only
  evidence;
- an explicit, content-addressed, single-run authorization binds the exact run
  and preregistration and permits research fitting only;
- immutable root-owned code, entrypoint, dependency, Python, Git, and release
  identities all agree with preregistration;
- fresh CPU, memory, disk, I/O, duplicate-writer, guarded-ingestion, and timing
  evidence proves the fit can finish with a reserved ingestion buffer;
- the exact no-shell argv, environment allowlist, idempotency key, checkpoint
  cadence, append-only output paths, and quarantine path are frozen;
- database writes, prediction persistence, recommendations, orders, ETF output,
  trading, and snapshot validation/promotion remain false.

`build_execution_authorization` produces only
`AUTHORIZED_NOT_STARTED`; the artifact records `launch_performed=false`. A
separate reviewed launcher must independently audit it before execution.

Lifecycle auditors require contiguous, identity-bound checkpoints, reject stale
progress and any downstream side effect, and accept terminal success only with
exact 474-target/four-fold reconciliation. Numerical or convergence failure is
preserved as a typed scientific failure with partial outputs quarantined; it
never authorizes threshold, model, sampler, lag, or depth changes.

Run the isolated tests with:

```text
python -m unittest discover -s model_fit_contract_impl -p "test_*.py" -v
```
