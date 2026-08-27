# Temporary nightly continuity controller

Status: **IMPLEMENTED and fixture-tested only**. Nothing in this directory has
been deployed, no production service has been changed, and Turso has not been
contacted.

## Contract

At `03:30 Asia/Jerusalem` every day, the controller reads a root-owned,
mode-0600, hash-pinned NYSE calendar artifact and selects the most recent
session whose real UTC close plus the configured settlement delay has passed.
This handles weekends, exchange holidays, early closes, and DST transitions
without deriving the session from the Israel wall-clock date. The calendar also
has an explicit UTC validity horizon; the default deployment contract requires
at least seven future days of coverage and fails closed before exhaustion.

It then runs a hash-pinned SELECT-only preflight executable and makes one pure,
fail-closed decision:

1. No snapshot exists: start exactly
   `codex-market-ingestion@YYYY-MM-DD.service`.
2. One unique STAGING snapshot exists with zero approvals/screenings: skip the
   writer and resume exactly at postflight.
3. A valid terminal handoff already exists: idempotent no-op.
4. An exact pipeline stage is already live: idempotent no-op.
5. Any duplicate, non-STAGING lifecycle, downstream output, failed unit,
   multiple active stage, stale evidence, unsafe legacy unit, or hash mismatch:
   fail closed without dispatch.

The only automatic successor chain is:

`ingestion -> SELECT-only postflight -> terminal handoff verification`

There is deliberately no baseline, model, recommendation, order, validation,
promotion, email, or trading successor. The inherited sniper/nightly/QA units
must remain disabled and inactive; runtime checks enforce this before dispatch.

## Liveness and guarded priority

The ingestion unit receives CPU/IO weight 900 and nice -5. A separate five-
minute watchdog requires one live pipeline unit, a nonzero MainPID, and a fresh
durable `progress.json` within the declared 900-second maximum interval. It
records append-only local JSONL evidence. Missing/stale progress, a failed unit,
or contradictory active stages exits nonzero and never restarts or duplicates
the writer. Before any dispatch, the controller enumerates every active
ingestion/postflight/handoff instance and rejects a different source session.
It also records and enforces CPU-load, available-memory, and free-disk gates.

## Immutable deployment procedure

1. Review and hash the controller, ingestion, handoff, preflight, and NYSE
   calendar artifacts.
2. Place executable releases in root-owned, non-mutable
   `/opt/codex-oracle/releases/<name>-<sha256>/` directories.
3. Render units with `render_units.py`; rendering rejects non-SHA release IDs,
   an existing output directory, unresolved placeholders, and any topology
   audit failure.
4. Create `/etc/codex-oracle/nightly-continuity.json` as root:root mode 0600,
   replacing every example placeholder with reviewed hashes. The separate
   read-only Turso environment file must also be root:root mode 0600.
5. Run the focused tests and topology audit in the immutable release.
6. Only after separate deployment approval, install the rendered units and
   enable the two temporary timers. Preserve the previous unit files as the
   rollback artifact.
7. Disable and remove both temporary timers when the migration completion gate
   is independently verified.

## Verification

Run from this directory:

```text
python -m unittest discover -v
```

The suite covers session selection across weekend/DST examples, calendar and
executable identity, SELECT-only evidence, duplicate/lifecycle contradictions,
idempotent decisions, failed-state retry prevention, PID/checkpoint liveness,
immutable rendering, exact topology, terminal handoff, safety hardening, and
guarded ingestion priority.
