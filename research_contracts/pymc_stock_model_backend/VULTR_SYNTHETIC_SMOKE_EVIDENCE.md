# Vultr synthetic PyMC graph/API smoke

Evidence stage: **OBSERVED for fixture graph/API compatibility only**.

- Environment: `/opt/antigravity/venv/bin/python`
- Python: 3.14.4
- PyMC: 6.1.0
- ArviZ: 1.2.0
- NumPy: 2.4.6
- Fixture: two targets, three independent target/source/lag edges, 126 rows per
  target; no production data and no Turso access.
- Observed graph: 14 free random variables; direction likelihood
  `direction_observed`; percentage-return likelihood `return_observed_pct`.
- Initial compiled log probability: finite.
- API smoke: one chain, five tune and five draws, deterministic seed 1729;
  `nuts={"max_treedepth": 5}` accepted by PyMC 6.1.0.
- Posterior shapes: direction `(1, 5, 2)` and return `(1, 5, 2)`.
- Durable rehearsal: two hash-linked checkpoints and one
  `TERMINAL_FIXTURE_SMOKE` readback; terminal SHA-256
  `f62b50e7b27173badc858ed1f499fb8c5e6dc01443376cd018953c87f01bc21c`.
- Complete isolated S08 contract tests on Linux: 93/93 passed in 37.915
  seconds. This includes the upstream execution and hierarchy contracts, the
  backend/runner, checkpoint/quarantine behavior, and the normalized-edge
  immutable reader with exact 474-target × 4-fold synthetic coverage.
- Normalized-edge negative cases reject payload/selection/manifest tamper,
  incomplete or duplicate coverage, purge overlap, stale or mismatched S07
  proof, unsafe keys, non-finite values, and later source mutation.
- Remote isolation: UUID-scoped `/tmp/codex-s08-pymc-fixture-*`; exact directory
  removed after the test.
- Production effects: zero database writes, zero persisted predictions, zero
  recommendations, zero orders, zero ETF output, zero trading, zero deployment.

This smoke proves that the concrete graph constructs, compiles, and traverses
the active PyMC API. It does **not** prove convergence, scientific validity,
canonical real 474-target/four-fold input completion, immutable release
identity, four-chain convergence, or real-fit authorization. Those remain
explicit gates.
