# Post-close ingestion scheduling — 2026-08-24

## Scope

This change schedules evidence-only EOD ingestion. It cannot run models,
generate recommendations, create orders, send email, or activate the sniper.
Production market/model tables remain governed by their separate validation
and promotion processes.

## Verified one-time job

The already installed `codex-market-ingestion-20260824-v2.timer` is enabled and
active. It is scheduled for `2026-08-25 00:30 Asia/Jerusalem` (`2026-08-24
21:30 UTC`) and targets the completed `2026-08-24` NYSE session. Its preflight
passed on 2026-08-24. The sniper, legacy nightly timer, and legacy QA timer were
all verified inactive and disabled.

An earlier status check incorrectly queried the nonexistent generic name
`antigravity-ingestion-guarded.timer`. Exact-unit inspection corrected the
record: the dated one-time timer was installed and scheduled.

## Durable replacement

`run_post_close_eod_ingestion.py` derives the latest completed session from the
NYSE calendar and UTC market-close timestamps. It requires a 30-minute grace
period, verifies protected services remain frozen, verifies secret-file
metadata, and invokes only the EOD revision stager.

The recurring timer uses `America/New_York` directly:

```text
Mon..Fri *-*-* 16:30:00 America/New_York
```

This avoids Israel/US daylight-saving offset assumptions. `Persistent=yes`
allows a missed invocation to be recovered by systemd. A process lock prevents
overlap.

The recurring unit is committed but must remain uninstalled/disabled until the
dated one-time job finishes and its Turso evidence is verified. Activating both
would create competing post-close jobs.

## Idempotency and failure behavior

- A complete provider/session evidence run with the exact controlled-universe
  row count is recognized independent of code hash and skipped.
- Partial evidence remains resumable and is never declared complete.
- Whole-command retry is bounded; Turso/provider failure exits nonzero.
- No incomplete session is selected.
- No CSV, Excel, SQLite, or Streamlit path is used.
