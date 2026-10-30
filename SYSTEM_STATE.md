# AntiGravity AI Brain (`SYSTEM_STATE.md`)
*Last Updated: October 30, 2026 (`v2.5-Deterministic-Lineage`)*

> **AI INSTRUCTION:** At the start of every session, read this file alongside `.agents/AGENTS.md` and `.agents/skills/anti_gravity_prime_directives/SKILL.md` to synchronize with the current systemic state.

---

## 1. Core Production Architecture & Prime Directives
1. **100% Turso Cloud Database SSOT:**
   - All production data resides exclusively in **Turso** (`capital_ledgers`, `pending_orders`, `etf_scorecards_master`, `yahoo_daily_prices`, `feature_lineage_audit`, `decision_lineage_audit`, `prod_vs_shadow_master`, `olympic_shootout_master`, `process_continuity`).
   - All database queries route through `database_manager.py`.
2. **Orchestration on Vultr VPS (`66.42.118.26`) via Prefect 3:**
   - **Prefect Orchestrator (`prefect_pipeline.py serve`)**: Manages all scheduled pipeline runs, pre-flight checks (`preflight_check.py`), and the hourly Zombie Hunter (`clean_ghosts.py`).
   - **Intraday Sniper (`intraday_tracker.py`)**: Polls live 1-minute bars every 3 minutes during NYSE hours (`09:30–16:00 EST`), executing VWAP breakouts, momentum shields, and VIX-scaled Take-Profit/Stop-Loss rules, with a `15:55 EST` EOD fallback.
   - **VIX Monitor (`vix_monitor.py`)**: Polls live `^VIX` continuously.
   - **FastAPI Server (`server.py` via `ag-uvicorn.service` on Port 80)**: Serves all 5 dashboard tabs and `/api/trace`.
3. **Seeded 2-Chain PyMC SV + Dual-Head & 7-Stage Lineage (`oracle_lineage_core.py` & `trace_decision.py`):**
   - Every prediction uses deterministic SHA-256 seeds (`SV` and `MAIN` stages, 2 chains, 1000 draws, 1000 tune).
   - Every persona decision and fractional Kelly allocation is evaluated through `oracle_lineage_core.evaluate_persona_decision()` and logged to `feature_lineage_audit` and `decision_lineage_audit`.
   - Any trade on any date (`2026-08-21`..`2026-10-30`) can be traced end-to-end via `trace_decision.py`.

---

## 2. Verified `$10,000.00`-Inception Ledger State (`2026-10-30` Live Session)
All 8 personas start at an exact **`$10,000.00`** inception balance and satisfy Double-Entry (`Cash + sum(Holdings) == Total_Equity`, diff = `$0.00`), Inter-Day Continuity (`Equity[t] == Equity[t-1] + sum(Daily_PnL[t])`, diff = `$0.00`), Check 3b (`>5%` single-day spike/drop audit), Check 4 (Anti-Flatline audit), and Check 5 (`$10,000.00` inception audit):
- **`Conservative` (Stock):** `2026-07-08` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,020.46`**, `+0.20%`)
- **`Neutral` (Stock):** `2026-07-08` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,245.70`**, `+2.46%`)
- **`Dynamic` (Stock):** `2026-07-08` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,248.77`**, `+2.49%`)
- **`BallsForBrains` (Stock):** `2026-06-26` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,176.36`**, `+1.76%`)
- **`ETF_Conservative` (ETF):** `2026-06-22` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,028.68`**, `+0.29%`)
- **`ETF_Neutral` (ETF):** `2026-06-22` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,169.19`**, `+1.69%`)
- **`ETF_Dynamic` (ETF):** `2026-06-25` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,140.32`**, `+1.40%`)
- **`ETF_BallsForBrains` (ETF):** `2026-06-29` (`$10,000.00`) $\to$ `2026-10-30` (**`$10,349.02`**, `+3.49%`)

---

## 3. Pre-Commit & Daily QA Protocol
Before any `git commit`, `git push`, or migration backup to `C:\Users\AviShemla\AG_BCK`, execute `py -u c:\Users\AviShemla\AntiGravity\qa_manager.py` and confirm `FINAL QA STATUS: 100% GREEN (ALL PASSED)` across all 9 QA scripts.
