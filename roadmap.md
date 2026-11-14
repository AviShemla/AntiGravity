# AntiGravity Project Roadmap & Master Task Checklist (`roadmap.md`)
*Last Updated: November 14, 2026 (`v2.8-Autonomous-Daily-And-Weekend-Cycle`)*

> **PHASE GATE CONDITION:** Execute and verify **7 consecutive zero-failure days (including a full weekend and post-weekend Monday market open)** at `100% GREEN` across all 9/9 QA suites (`qa_manager.py`) and 12/12 Task Auditor checks (`qa_task_auditor.py`) on **Vultr (`66.42.118.26`)** and **Turso**. Once that full 7-day cycle completes cleanly with zero manual intervention, begin executing **Part 2 (Phase 3 Pending Model & Execution Enhancements)** below.

---

## ✅ PART 1: Completed & Active in Production (`Phase 1 & Phase 2 — 100% VERIFIED`)

| # | Task / Milestone | Status | Primary Files & Verification Proof |
| :---: | :--- | :---: | :--- |
| **1.1** | **100% Turso Cloud SSOT Migration** (All 8 Personas, Scorecards, Pending Orders, Daily Prices & Arena Tables) | ✅ **DONE** | `database_manager.py`, `server.py` |
| **1.2** | **7-Stage Deterministic Source-to-Target Lineage & Proof Receipt** (Raw Bar $\to$ Lagged Features $\to$ Z-Score $\to$ 2-Chain Seeded PyMC SV + Dual-Head $\to$ Bounded Kelly $\to$ Staged Order $\to$ Double-Entry Ledger) | ✅ **DONE** | `oracle_lineage_core.py`, `trace_decision.py`, `/api/trace` |
| **1.3** | **Exact `$10,000.00` Inception Reconciliation & Pre-Inception Flatline Purge** across all 8 Stock & ETF Personas (`diff = $0.00`) | ✅ **DONE** | `qa_financial_audit.py`, `qa_api_health.py` |
| **1.4** | **Unified Arena Volatility Envelope Calibration & 8-Model Tracking** (`PROD_Bayesian_SV`, `EL_CAP`, `EL_VOLTI`, `Shadow_Transformer`, `Sandbox_V1`, `Shadow_LSTM`, `Shadow_ETF_Whale` [Task #1], `Shadow_Neural_Safety` [Task #2]) | ✅ **DONE** | `prod_vs_shadow_tracker.py`, `qa_dashboard_integrity.py` (Checks 5A/5B/5C/5D) |
| **1.5** | **Dedicated Prefect 3 Server (`127.0.0.1:4200`) & 8 Autonomous Deployments on Vultr (`66.42.118.26`)** (Daily Nightly Pipeline, Weekend DL Trainers, Pre-Market Health, 15m API Health, Hourly Maintenance + Zombie Hunter, Market Daemons) | ✅ **DONE** | `prefect_pipeline.py`, `qa_task_auditor.py` (`[QA 11]` Prefect Guard) |
| **1.6** | **Full 9-Script Zero-Trust QA Suite (`9/9 Suites`, `11/11 Task Checks`), Continuity Interlock Guard (`[QA 10]`), & Zero-Prompt SSH Automation** | ✅ **DONE** | `qa_manager.py`, `export_etf_broker_excel.py`, `execute_daily_migration.py`, `vultr_status_and_heal.py` |

---

## 🗓️ PART 1B: 7-Day Consecutive Autonomous Burn-In Gate (Counter Reset to `0/7` on Tuesday `2026-11-10`)

- **Current Consecutive Clean Days Counter**: **`4 / 7`** *(Wednesday `2026-11-11` (`1/7`), Thursday `2026-11-12` (`2/7`), Friday `2026-11-13` (`3/7`), and Saturday `2026-11-14` (`4/7` — `01:00 UTC` Nightly Pipeline + `14:00 UTC` Weekend DL Trainers) all completed 100% hands-free and passed `9/9 QA Suites` & `12/12 Task Checks` with zero manual intervention)*
- [x] **Day 1 — Wednesday `2026-11-11`**: Post-Close Nightly Pipeline (`01:00 UTC` Wed) + Live Intraday Sniper (`09:30–16:00 EST`) + `9/9 QA Green` (`12/12 Task Checks`) (`1/7` ✅ **COMPLETE**).
- [x] **Day 2 — Thursday `2026-11-12`**: Post-Close Nightly Pipeline (`01:00 UTC` Thu) + Live Intraday Sniper (`09:30–16:00 EST`) + `9/9 QA Green` (`12/12 Task Checks`) (`2/7` ✅ **COMPLETE**).
- [x] **Day 3 — Friday `2026-11-13`**: Post-Close Nightly Pipeline (`01:00 UTC` Fri) + Live Intraday Sniper (`09:30–16:00 EST`) + `9/9 QA Green` (`12/12 Task Checks`) (`3/7` ✅ **COMPLETE**).
- [x] **Day 4 — Saturday `2026-11-14`**: Post-Close Nightly Pipeline (`01:00 UTC` Sat, staging Monday `2026-11-16`) + Autonomous Weekend Protocol (`weekend-trainers` at `14:00 UTC`) + `9/9 QA Green` (`4/7` ✅ **COMPLETE**).
- [ ] **Day 5 — Sunday `2026-11-15`**: Full Sunday Autonomous Maintenance & API Health QA + `9/9 QA Green` (`5/7`).
- [ ] **Day 6 — Monday `2026-11-16`**: Zero-Touch Post-Weekend Market Open Sniper Execution (`09:30–16:00 EST`) + `9/9 QA Green` (`6/7`).
- [ ] **Day 7 — Tuesday `2026-11-17`**: Post-Close Nightly Pipeline (`01:00 UTC` Tue) + Live Intraday Sniper (`09:30–16:00 EST`) + `9/9 QA Green` (`12/12 Task Checks`) (`7/7 COMPLETE`).

---

## ⏳ PART 2: Queued Tasks Yet To Work On (`Phase 3 — Model & Execution Improvements`)
*(To begin immediately after the 1-week + weekend burn-in gate above completes at 100% GREEN)*

| Task # | Phase 3 Enhancement | Goal & Mathematical Mechanism | Status |
| :---: | :--- | :--- | :---: |
| **Task 3.1** | **Hierarchical Deep-Learning Priors into PyMC (`alpha_dir`)** | Feed the out-of-sample `Shadow_Transformer` / `Shadow_LSTM` probability logits directly into the PyMC Dual-Head `alpha_dir` prior as an informative neural prior (combining Deep Learning sequence recognition with Bayesian Stochastic Volatility). | ⏳ **PENDING (Next Phase)** |
| **Task 3.2** | **Variable Multi-Lag Causal Chain Network (`1..5` Links, Lags `1..7`)** | Upgrade the stock lead-lag screener to evaluate non-consecutive multi-edge causal lag tuples (e.g., lags `(7, 5, 2)`) on strictly isolated training splits with out-of-sample walk-forward validation, and feed statistically significant stock posteriors directly into ETF priors. | ⏳ **PENDING (Next Phase)** |
| **Task 3.3** | **Regime-Switching Meta-Model ("Traffic Cop")** | Build a dynamic regime classifier using `^VIX`, `^TNX` (10Y Treasury yield trend), and S&P 500 market breadth to dynamically shift weight between `PROD_Bayesian_SV` (aggressive stock alpha), `Shadow_ETF_Whale` (sector rotation), and `Shadow_Neural_Safety` (defensive cash/low-beta shield). | ⏳ **PENDING (Next Phase)** |
| **Task 3.4** | **Monday / Day-of-Week Damping Factor & ATR Trailing Stops** | Use the Trade Autopsy day-of-week vulnerability metrics to automatically tighten the fractional Kelly multiplier on high-gap days (such as Mondays) and upgrade `intraday_tracker.py` with Average True Range (`ATR_14d`) dynamic trailing stops alongside VWAP. | ⏳ **PENDING (Next Phase)** |
| **Task 3.5** | **Cryptographic NetCDF Posterior Trace Archival & Paper-to-Live Execution Bridge** | Persist compressed ArviZ `.nc` posterior traces (`model_lineage` table) and prepare a shadow brokerage execution adapter (Interactive Brokers / Alpaca paper API) with a global kill-switch. | ⏳ **PENDING (Next Phase)** |
