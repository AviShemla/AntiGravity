# S08 concrete PyMC backend and immutable-runner scaffold

This isolated package implements the previously missing concrete PyMC graph for
the governed independent-edge hierarchy. It uses two jointly sampled heads:
Bernoulli-logit direction and Student-t percentage return. Target intercepts and
independent target/source/lag coefficients are partially pooled. Ragged target
depths are packed explicitly; tuple position never determines lag identity.

Every numeric prior and sampler choice is content-addressed. Four deterministic
chains, at least 1,000 tune and 1,000 draws, NUTS tree-depth evidence, R-hat,
bulk/tail ESS, BFMI, and divergences are extracted. The existing outer boundary
still rejects incomplete ticker coverage, failed convergence, or any database,
prediction, recommendation, order, ETF, or trading side effect.

PyMC and ArviZ are lazy imports. Importing the package cannot fit a model. The
included runner permits only fixture execution against an already-built
`AUTHORIZED_NOT_STARTED` artifact and performs no file or database I/O.

The fixture rehearsal layer adds a separate durable store restricted to newly
created `codex-s08-fixture-*` paths. Checkpoints are canonical,
content-addressed, hash-linked, exclusively created, and fsynced. A sampler
exception is re-raised after a terminal quarantine marker is durably recorded.
Fixture terminals always declare `scientific_evidence=false` and
`convergence_claimed=false`.

The normalized-edge input boundary is also isolated and injection-only. It
binds every manifest to the S07 preregistration and readback hashes, requires
exactly 474 targets by four leakage-free folds, verifies the fixed purge and
fold geometry, content-addresses each canonical independent-edge selection,
and rehashes compact binary fold payloads on every read. Synthetic contract
tests reject overlap, tamper, incomplete or duplicate coverage, stale S07
evidence, non-finite values, and time-of-check/time-of-use source mutation.
It has no filesystem, network, database, or Turso client.

The Linux rehearsal boundary additionally content-addresses the Python
executable, PyMC, PyTensor, ArviZ, NumPy, BLAS identity, and distribution
records. Synthetic convergence evidence requires the unchanged frozen sampler:
four chains, at least 1,000 tune and 1,000 draws, unique preregistered seeds,
and every existing R-hat/ESS/BFMI/divergence/tree-depth gate. A low-priority
filesystem runner scaffold rechecks fresh resources and guarded-ingestion
buffer both before and after execution, quarantines any yielded result, and has
an independent exact-terminal auditor. The scaffold contains no process
launcher and cannot authorize real data.

This is **IMPLEMENTED, fixture-tested, and graph/API smoke-observed** under
the current Vultr dependency closure. It is not deployed or authorized for real
data. The smoke used one chain with five tune/five draws solely to prove graph
construction and PyMC API compatibility; it is not convergence evidence.
