# S02 recurring deployment inputs — isolated implementation

Status: **IMPLEMENTED and fixture-tested only**. Nothing here is deployed; no
Turso write, network call, unit change, or snapshot lifecycle change is made.

## SELECT-only idempotency preflight

`turso_idempotency_preflight.py` is a root-only executable that:

- consumes the protected systemd process environment used by the continuity
  service, or an explicitly supplied root-owned mode-0600 environment file,
  without printing secrets;
- normalizes only `libsql://host` or exact HTTPS `/v2/pipeline` endpoints;
- exposes only a SELECT reader and rejects non-SELECT SQL before transport;
- runs three fixed, hash-bound statements for exact MARKET_FEATURES snapshot
  cardinality and downstream approval/screening counts;
- emits canonical, write-once, root-owned mode-0600
  `codex-market-ingestion-idempotency-preflight-v1` evidence compatible with
  `research_contracts/nightly_continuity` semantics;
- preserves duplicate cardinality so the controller fails closed rather than
  selecting a snapshot silently.

## NYSE calendar artifact

`nyse_calendar_artifact.py` builds and independently reconstructs the exact
`codex-nyse-session-calendar-v1` consumed by the continuity controller. The
checked-in canonical ruleset covers 2026, enumerates ten full closures and
two early closes (November 27 and December 24), records its SHA-256 and NYSE
primary-source references, uses an
explicit post-2007 U.S. DST algorithm, and has no mutable runtime package
dependency. The output contains actual UTC opens/closes and an explicit
validity horizon through `2026-12-31T23:59:59Z`.

The ruleset was checked against NYSE's primary Holidays and Trading Hours page
and its 2026 Yearly Trading Calendar. Those sources do **not** designate July 2,
2026 as an early close; it is a regular 16:00 Eastern / 20:00 UTC session. The
official-source identities remain embedded in the hash-pinned provenance.

## Tests

```powershell
python -m unittest -v s02_recurring_deployment_impl.test_s02_inputs
```

Tests cover exact consumer compatibility, query and result shapes, duplicate
and downstream contradictions, endpoint/SQL hardening, canonical/token-free
evidence, weekends, ten holidays, both early closes, both 2026 DST
transitions, exact 251-session coverage, horizon enforcement, deterministic
rebuild, hash/tamper rejection, explicit July-2 normal-close regression, and
direct continuity-controller loading.
