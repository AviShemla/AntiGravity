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

## Disabled-only recurring deployment contract

`disabled_only_installer.py` defines the root-owned production contract for a
future deployment of the verified calendar, SELECT-only preflight, controller,
configuration, and seven recurring unit files. It is intentionally not a unit
activator. Its manifest pins every artifact by SHA-256, binds executable
release paths to that hash, requires exact root-owned production paths/modes,
and declares every recurring and inherited safety unit `inactive` and
`disabled`.

The installer first inspects all ten guarded units and verifies and backs up
every input. It then writes a canonical, write-once rollback manifest before
any deployment-target mutation, atomically installs artifacts, and re-reads
every artifact and unit state. A separate write-once completion record
distinguishes prepared rollback evidence from a completed install. The only
systemd command implemented is read-only `systemctl show`; no enable, start,
restart, stop, or daemon-reload command exists. The CLI additionally requires
an explicit `--apply-disabled-only` flag and Linux root execution.

All automated coverage uses workspace-owned fixture roots. It does not deploy,
contact Turso, alter snapshot lifecycle state, or modify tonight's units.
Windows fixture mode emulates only the writable/read-only bit because Windows
cannot represent full POSIX modes; production audit is Linux-only and requires
exact POSIX modes plus UID/GID 0.

## Concrete release/deployment assembly

`release_deployment_assembly.py` is the deterministic join contract for the
disabled deployment. It independently re-reads three canonical immutable
release manifests, the controller implementation, all five runtime runners,
the calendar/ruleset, SELECT-only preflight, controller configuration, and the
exact seven rendered units. Runner targets are bound to release-manifest IDs;
unit bodies must reference those exact targets and may not contain mutable
aliases, unresolved placeholders, or systemd activation commands.

The resulting canonical assembly embeds a hash-pinned manifest accepted by the
disabled-only installer and cross-binds its deployment ID and hash to the exact
rollback and audit contract identities. Assembly itself has no subprocess or
network surface. Its only write operation is optional canonical write-once
evidence. Immutable release directories must already have been built and
independently verified; assembly does not deploy them or authorize activation.
