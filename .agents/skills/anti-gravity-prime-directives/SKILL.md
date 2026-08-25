---
name: anti-gravity-prime-directives
description: AntiGravity QA companion for evidence-backed Turso, model, dashboard, and infrastructure verification; subordinate to repository-root AGENTS.md for operating authority.
---

# 🛡️ AntiGravity Evidence and QA Companion

This is a reusable QA companion. Repository-root `AGENTS.md` is the current operational authority and wins on conflict.

---

## 0. 🏆 OPERATING MODE AND AUTHORITY

Current mode is **FROZEN/RESEARCH**. The following are verification criteria
for a future approved automated paper-trading morning; they are not standing
instructions to start services, run models, stage orders, write Turso, or send
email. Activation requires the mode-transition approval defined in root
`AGENTS.md`.

1. **Intraday Sniper Execution:** Live trade day sniper (`ag-sniper.service` on Vultr) executed successfully, monitored price ticks, and guarded all active positions.
2. **Nightly Pipeline & Staging Execution:** Night run executed cleanly—models re-trained/scored, Turso DB updated, and pending orders for today's market open successfully staged for all 8 personas in `pending_orders`.
3. **Dashboard Visual QA & 100% Sync:** All 5 dashboard tabs visually inspected via Playwright screenshot QA (`capture_all_web_tabs.py`), fully in sync, and presenting data continuously without gap artifacts, chart crashes, or missing orange pending badges.
4. **Email Report Sync:** Morning daily report emails sent exclusively via Native Gmail SMTP (`smtp.gmail.com:465`) with exact figures in 100% perfect sync with Turso DB and the live Web Dashboard.

---

## 1. 🔒 MASTER PRIME DIRECTIVES & VERIFICATION RULES

1. **Strict 100% Database Table Backing Rule:**
   - ABSOLUTELY NO CSV or Excel files allowed as data sources or fallbacks!
   - Every single answer regarding trade recommendations, holdings, pending orders, or portfolio status **MUST be backed by a direct SQL query to Turso DB tables** (`daily_holdings`, `pending_orders`, `etf_scorecards_master`, `prod_vs_shadow_master`).
   - Never guess, summarize from memory, or use unverified local variables.

2. **Zero-Hallucination Policy:**
   - NEVER answer questions about system architecture, configuration, pipelines, or logic based on memory or assumptions.
   - YOU MUST ALWAYS use physical tools (`grep_search`, `view_file`, raw DB queries) to verify the exact code/state BEFORE answering.
   - Apply this to every status, progress percentage, ETA, completion,
     scheduler, test, deployment, service, database, model, and dashboard claim.
   - State the observation time, evidence type/source, checked identifier, and
     observed result. If current evidence is absent, stale, contradictory, or
     incomplete, report UNKNOWN or UNVERIFIED; never infer the missing fact.
   - Derive percentages from an explicit denominator of individually verified
     milestones. Do not estimate them from time spent, apparent activity, or
     prior conversation.
   - Treat configured, running, completed, and verified as distinct states and
     report only the state directly proven.
   - Report a scheduler as ACTIVE only after reading back its persisted
     configuration and observing a representative test firing. A suggestion
     card, accepted command, or creation response is not proof that it will
     execute.

3. **Continuity, Liveness, and Stale-Work Control:**
   - Never say or imply that work continues after the current Codex turn unless
     a persistent worker is physically verified on its execution host.
   - RUNNING requires a fresh timestamp, host, PID or systemd unit, exact
     command/job identifier, start time, and a durable log or checkpoint with a
     current progress marker.
   - If those facts are absent, report NOT RUNNING and state that work stops
     when the turn ends. A plan, intent, open terminal, old PID, or prior status
     is not liveness evidence.
   - Long jobs must run on Vultr or another explicitly approved persistent host,
     be restart-safe and idempotent, and write append-only logs plus resumable
     checkpoints. They must not depend on the user's laptop, browser, Wi-Fi, or
     an open chat.
   - Re-read the worker and newest checkpoint for every update. Never recycle a
     previous observation as current status.
   - Declare the maximum expected checkpoint interval before launch. If the
     checkpoint is older than that interval, mark the job STALLED, inspect
     process/exit state and logs, and report the cause. Do not silently wait or
     automatically restart it.
   - Use bounded, declared retries. The same failure repeating is a blocker.
   - Calculate ETA only from a timestamped completed/total count and measured
     recent checkpoint throughput; show the calculation and a range. Otherwise
     report ETA UNKNOWN.
   - Completion requires terminal exit evidence, expected output/count checks,
     and independent readback or QA. A vanished process is not proof.
   - Before ending any turn that mentions ongoing work, classify it as VERIFIED
     PERSISTENT, COMPLETE, BLOCKED/STALLED, or NOT RUNNING and include the
     corresponding evidence.
   - When an already authorized job fails or stalls, do not wait passively and
     do not blindly restart it. Preserve evidence, stop deterministic retry
     loops, identify the smallest reversible repair, test it with a focused
     check or preflight, and continue the same idempotent job automatically
     when the remedy stays within its existing approved scope and does not
     weaken a data, model, risk, or capital-safety gate.
   - A rule prohibiting automatic restart prohibits an unexamined retry; it
     does not prohibit diagnosis, safe repair, verification, and continuation
     of the already approved workflow. Ask before continuing only when the
     remedy expands scope, weakens a gate, changes model/risk/execution
     semantics, performs destructive data/schema work, handles a new secret,
     or creates a material new external commitment.

4. **Dashboard X-Axis, Visual Anomaly & NYSE Market Hours Max Date Verification Rule:**
   - Whenever checking or verifying the Dashboard UI for correctness, you MUST explicitly inspect the chart lines for unnatural vertical drops, non-trading gap artifacts, label truncation, or syntax error banners (e.g. Mermaid)!
   - **CRITICAL EXPECTED MAX DATE RULE:** NEVER rely solely on Turso DB to check expected dates (the DB could be fed stale or corrupted data!). Expected max date MUST be calculated independently using real-world NYSE market hours (`pandas_market_calendars`) vs current local time:
     * **Pre-Market (00:00 - 16:30 Israel IDT / 09:30 NYC EST):** Settled Max Date = Latest completed NYSE session date (e.g. `2026-08-19`). Pending Staged Date = Today's session (`2026-08-20`).
     * **Regular Market Hours (16:30 - 23:00 Israel IDT / 09:30 - 16:00 NYC EST):** Settled Max Date = Yesterday's session. Staged Status = Live Intraday Execution in progress.
     * **Post-Market (23:00 - 23:59 Israel IDT / 16:00 - 24:00 NYC EST):** Settled Max Date = Today's session.
   - Mathematically prove that every dashboard tab matches this exact NYSE business logic max date.

5. **Zero Polling Loop & AI Credit Conservation:**
   - NEVER run endless or polling loops (`manage_task` in a tight loop).
   - ALWAYS use `schedule` or system reactive wakeups.
   - Batch multiple sequential calls into a single execution script to save AI credit tokens.

6. **Spike / Drop Double-Validation Rule (>5% Delta):**
   - Any model or portfolio equity spike or drop greater than 5% on a single date **MUST BE DOUBLE-VALIDATED** by pulling a fresh, direct Yahoo Finance price extract (`yfinance` / `download_ticker_with_failover`) for the target holding on that exact date.
   - NEVER assume or report an unverified market surge/crash without physically cross-referencing the underlying asset's real-world price data.

7. **First Contact / Morning Initialization Protocol:**
   - On the very first user prompt of a new session/day, the agent MUST read this SKILL document, run `/learn`, and explicitly report to the user that all Prime Directives have been loaded before answering any prompt.

8. **Model Specification Equivalence:**
   - Chain length and per-edge lag are separate. Candidate lags may be independent, non-consecutive, non-monotonic, and above five when included in the preregistered search domain.
   - Before execution, compare the actual configuration with the approved lag domain, chain semantics, cutoff, universe, and validation design. A mismatch blocks execution; a discovered mismatch marks the run `FAILED` and makes partial outputs ineligible for promotion or orders.

9. **Prediction Transparency:**
   - Keep raw Bayesian posterior quantities separate from production eligibility.
   - For every stock prediction, and later every ETF prediction, retain an auditable gate table for historical AntiGravity, strict Codex research, and proposed balanced policies. A blocked trade does not erase the model output.

10. **Snapshot and Provider Lineage:**
   - Bind every run to an immutable market-data snapshot. Record provider, ticker universe, availability cutoff, transformations, feature/lag specification, code/config versions, sampler, and seed policy.
   - A Yahoo/Tiingo/other-provider fallback must be explicit in lineage and must never silently mix or replace observations within an approved snapshot.

11. **Fresh Quarantine:**
    - Legacy quarantine membership is historical evidence only. The repaired stock and ETF systems start with empty quarantine state; every future entry/release records ticker, scope, reason code, evidence, date, and policy version.

---

## 2. ⚡ INFRASTRUCTURE & DAEMON PROTOCOLS

1. **Intraday Sniper Guarding (`ag-sniper.service`):**
   - Strictly forbidden from assuming a background daemon is healthy just because its parent orchestrator ran successfully.
   - Explicitly query Vultr server or live API endpoints to verify live trade execution.
   - Preserve the service capability, but keep it inactive in FROZEN/RESEARCH.
     Starting it requires an explicitly approved paper/live mode and all
     pre-execution gates in root `AGENTS.md`.

2. **Deadlocked Local Task Cleanup:**
   - If a background task querying Turso via `libsql_client` hangs without returning, explicitly terminate it (`manage_task(Action='kill')`) to prevent credit drain and memory leaks.

3. **Single Process Enforcement:**
   - `intraday_tracker.py` must run as EXACTLY 1 process on Vultr to prevent double FD leaks and race conditions.

4. **Sole Email Channel (Native Gmail SMTP SSL):**
   - ABSOLUTELY NO Windows Outlook COM / win32com automation!
   - 100% of email notifications and daily reports MUST use `email_utils.send_native_email()` via Gmail SMTP (`smtp.gmail.com:465`).

---

## 3. 🛡️ SPECIALIZED MULTI-AGENT QA ARCHITECTURE (ZERO-TOLERANCE PROTOCOL)

When the user requests an audit and the risk/scope justifies delegation, the QA
work may be divided among the following specialized roles. This section does
not require spawning agents or running the audit automatically:

The owner also authorizes bounded technical sub-agents for an AntiGravity
incident or migration task when independent parallel diagnosis, test design,
read-only Turso auditing, or service/log inspection materially shortens the
critical path. Sub-agents receive no broader production authority than the
parent task; production mutation, credential handling, and final recovery
decisions remain with the primary agent, and every finding must be reconciled
against direct evidence.

1. **`qa_master_orchestrator` (Lead Coordinator):**
   - Coordinates all specialized QA auditors, aggregates proofs, and generates the unified Morning Clearance Report.
   - Forbids issuing GREEN status until all 4 sub-auditors physically confirm zero defects with raw physical proofs.

2. **`qa_visual_auditor` (Visual & UI Inspector):**
   - Conducts Playwright screenshot QA across all 5 dashboard tabs.
   - Inspects for chart spikes/drops (>5% delta), non-trading gap artifacts, label truncation, and iframe Mermaid syntax errors.

3. **`qa_data_continuity_auditor` (Mathematical Continuity & Balance Auditor):**
   - Independently calculates NYSE market business day continuity (via `pandas_market_calendars`) vs Israel IDT / EST time.
   - Mathematically recalculates missing trading sessions against real historical market prices (NEVER forward-filling flat lines!).
   - Mathematically verifies `starting_cash + sum(PnL) == total_equity` across all 8 personas in Turso DB and backend endpoints.

4. **`qa_pipeline_model_auditor` (Pipeline Extraction & Model Integrity Auditor):**
   - Audits Yahoo Finance / Tiingo data extraction logs to verify zero missing OHLCV bars or corrupt zeroes.
   - Scans 100% of scorecards, prediction arrays, and staged `pending_orders` to ensure ZERO NaN, Null, Inf, or degenerate probabilities (P(UP) out of [0, 1]).

5. **`qa_infrastructure_daemon_auditor` (Infrastructure, Daemon & Execution Sentinel):**
   - Physically audits Vultr cloud daemons (`ag-sniper.service`), ensuring active price tick monitoring and zero duplicate PIDs.
   - Audits server ports (port 80 Uvicorn/FastAPI), memory footprint, cron pipelines, and strictly enforces 100% Native Gmail SMTP SSL (smtp.gmail.com:465).

---

## 4. 🛠️ REUSABLE AUDIT RULES

- Run audit tools only from the canonical Vultr-hosted Git worktree or another
  explicitly approved execution environment; stale Windows-local and Gemini
  scratch paths are not authoritative.
- Query Turso directly for holdings/order/model facts and record the query,
  cutoff, row counts, and returned identifiers without exposing credentials.
- Dashboard claims require live API evidence plus visual inspection of every
  affected tab, including X-axis/session continuity.
- Audits are read-only unless the user separately approves a scoped repair.
