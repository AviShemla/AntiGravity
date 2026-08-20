---
name: anti_gravity_prime_directives
description: Master Single Source of Truth (SSOT) Prime Directives, Zero-Hallucination rules, and 100% Turso DB Table Backing policies for AntiGravity operations.
---

# 🛡️ AntiGravity Master Prime Directives (SSOT)

This document is the **Single Source of Truth (SSOT)** for all operational rules, financial credit safety constraints, and execution protocols in the AntiGravity system.

---

## 0. 🏆 DAILY MORNING PRIME GOAL (VERIFICATION CRITERIA FOR PERFECT GREEN)

Every single morning before market open, the agent MUST verify and achieve 100% GREEN status across all 4 mandatory victory conditions:

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

3. **Dashboard X-Axis, Visual Anomaly & NYSE Market Hours Max Date Verification Rule:**
   - Whenever checking or verifying the Dashboard UI for correctness, you MUST explicitly inspect the chart lines for unnatural vertical drops, non-trading gap artifacts, label truncation, or syntax error banners (e.g. Mermaid)!
   - **CRITICAL EXPECTED MAX DATE RULE:** NEVER rely solely on Turso DB to check expected dates (the DB could be fed stale or corrupted data!). Expected max date MUST be calculated independently using real-world NYSE market hours (`pandas_market_calendars`) vs current local time:
     * **Pre-Market (00:00 - 16:30 Israel IDT / 09:30 NYC EST):** Settled Max Date = Latest completed NYSE session date (e.g. `2026-08-19`). Pending Staged Date = Today's session (`2026-08-20`).
     * **Regular Market Hours (16:30 - 23:00 Israel IDT / 09:30 - 16:00 NYC EST):** Settled Max Date = Yesterday's session. Staged Status = Live Intraday Execution in progress.
     * **Post-Market (23:00 - 23:59 Israel IDT / 16:00 - 24:00 NYC EST):** Settled Max Date = Today's session.
   - Mathematically prove that every dashboard tab matches this exact NYSE business logic max date.

4. **Zero Polling Loop & AI Credit Conservation:**
   - NEVER run endless or polling loops (`manage_task` in a tight loop).
   - ALWAYS use `schedule` or system reactive wakeups.
   - Batch multiple sequential calls into a single execution script to save AI credit tokens.

5. **Spike / Drop Double-Validation Rule (>5% Delta):**
   - Any model or portfolio equity spike or drop greater than 5% on a single date **MUST BE DOUBLE-VALIDATED** by pulling a fresh, direct Yahoo Finance price extract (`yfinance` / `download_ticker_with_failover`) for the target holding on that exact date.
   - NEVER assume or report an unverified market surge/crash without physically cross-referencing the underlying asset's real-world price data.

6. **First Contact / Morning Initialization Protocol:**
   - On the very first user prompt of a new session/day, the agent MUST read this SKILL document, run `/learn`, and explicitly report to the user that all Prime Directives have been loaded before answering any prompt.

---

## 2. ⚡ INFRASTRUCTURE & DAEMON PROTOCOLS

1. **Intraday Sniper Guarding (`ag-sniper.service`):**
   - Strictly forbidden from assuming a background daemon is healthy just because its parent orchestrator ran successfully.
   - Explicitly query Vultr server or live API endpoints to verify live trade execution.

2. **Deadlocked Local Task Cleanup:**
   - If a background task querying Turso via `libsql_client` hangs without returning, explicitly terminate it (`manage_task(Action='kill')`) to prevent credit drain and memory leaks.

3. **Single Process Enforcement:**
   - `intraday_tracker.py` must run as EXACTLY 1 process on Vultr to prevent double FD leaks and race conditions.

4. **Sole Email Channel (Native Gmail SMTP SSL):**
   - ABSOLUTELY NO Windows Outlook COM / win32com automation!
   - 100% of email notifications and daily reports MUST use `email_utils.send_native_email()` via Gmail SMTP (`smtp.gmail.com:465`).

---

## 3. 🛡️ SPECIALIZED MULTI-AGENT QA ARCHITECTURE (ZERO-TOLERANCE PROTOCOL)

To eliminate false "100% GREEN" clearances and guarantee empirical data accuracy, the morning audit is divided into 4 specialized subagents led by a Master QA Orchestrator:

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

## 4. 🛠️ REUSABLE EXECUTABLE AUDIT TOOLS

- **Pre-Market & Holdings Execution Audit (All 8 Personas):** `py C:\Users\AviShemla\AntiGravity\print_intraday_execution_table.py` *(Supports optional `--date YYYY-MM-DD` parameter. If omitted, dynamically queries `MAX(date)` from Turso DB with ZERO hardcoded dates).*
- **Full Dashboard Screenshot QA:** `py C:\Users\AviShemla\.gemini\antigravity\brain\01e9aa77-80c5-489b-8bac-9eba71ae877f\scratch\capture_all_5_tabs.py`

