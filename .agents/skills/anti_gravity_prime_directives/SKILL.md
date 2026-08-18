---
name: anti_gravity_prime_directives
description: Master Single Source of Truth (SSOT) Prime Directives, Zero-Hallucination rules, and 100% Turso DB Table Backing policies for AntiGravity operations.
---

# 🛡️ AntiGravity Master Prime Directives (SSOT)

This document is the **Single Source of Truth (SSOT)** for all operational rules, financial credit safety constraints, and execution protocols in the AntiGravity system.

---

## 1. 🔒 MASTER PRIME DIRECTIVES & VERIFICATION RULES

1. **Strict 100% Database Table Backing Rule:**
   - ABSOLUTELY NO CSV or Excel files allowed as data sources or fallbacks!
   - Every single answer regarding trade recommendations, holdings, pending orders, or portfolio status **MUST be backed by a direct SQL query to Turso DB tables** (`daily_holdings`, `pending_orders`, `etf_scorecards_master`, `prod_vs_shadow_master`).
   - Never guess, summarize from memory, or use unverified local variables.

2. **Zero-Hallucination Policy:**
   - NEVER answer questions about system architecture, configuration, pipelines, or logic based on memory or assumptions.
   - YOU MUST ALWAYS use physical tools (`grep_search`, `view_file`, raw DB queries) to verify the exact code/state BEFORE answering.

3. **Dashboard X-Axis & Visual Anomaly Verification Rule:**
   - Whenever checking or verifying the Dashboard UI for correctness, you MUST explicitly inspect the chart lines for unnatural vertical drops, non-trading gap artifacts, or label truncation!
   - Mathematically prove that the latest date in the database perfectly matches the latest date rendered on the chart's X-axis (`capture_all_web_tabs.py`).

4. **Zero Polling Loop & AI Credit Conservation:**
   - NEVER run endless or polling loops (`manage_task` in a tight loop).
   - ALWAYS use `schedule` or system reactive wakeups.
   - Batch multiple sequential calls into a single execution script to save AI credit tokens.

5. **First Contact / Morning Initialization Protocol:**
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

## 3. 🛠️ REUSABLE EXECUTABLE AUDIT TOOLS

- **Pre-Market & Holdings Execution Audit:** `py C:\Users\AviShemla\AntiGravity\print_intraday_execution_table.py`
- **Full Dashboard Screenshot QA:** `py C:\Users\AviShemla\.gemini\antigravity\brain\01e9aa77-80c5-489b-8bac-9eba71ae877f\scratch\capture_arena_full.py`
