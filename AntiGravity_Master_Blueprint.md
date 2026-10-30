# 🌌 THE ANTIGRAVITY MASTER BLUEPRINT (v2.5 Deterministic Lineage)
**System Reconstruction, 7-Stage Traceability & Cloud Architecture Manual**
*Last Updated: October 30, 2026 (`v2.5-Deterministic-Lineage` — 100% Turso Cloud SSOT, $10,000.00 Inception Reconciliation & 9/9 QA Green)*

> [!IMPORTANT]
> **To any future AI Agent reading this:** This document is the authoritative architectural blueprint for **The ORACLE (AntiGravity)**. It documents the exact mathematical formulas, 100% **Turso** cloud database tables, **Vultr + Prefect 3** orchestration topology, 8-Persona Fractional Kelly sizing gates, and 7-stage deterministic source-to-target lineage system (`oracle_lineage_core.py` & `trace_decision.py`).

---

## 1. Core Purpose & Philosophy
**The ORACLE (AntiGravity)** is an autonomous, cloud-native quantitative trading and capital-allocation system operating across **Single Stocks** (S&P 500 VIP Universe) and **Multi-Sector / Thematic ETFs**.
- **Mathematical Core:** Seeded 2-chain **Bayesian PyMC Stochastic Volatility (`GaussianRandomWalk`) + Dual-Head (Logistic Direction + Student-T Magnitude)** MCMC sampling via `PyTensor NUTS`.
- **Single Canonical Decision Gate (`oracle_lineage_core.py`):** Every persona decision (`BUY`, `HOLD_CARRYOVER`, `SELL`, `HOLD`), fractional Kelly allocation (`applied_kelly`), and deterministic MCMC seed (`SV` & `MAIN`) is computed through `oracle_lineage_core.py`.
- **100% Turso Cloud SSOT:** All production state resides exclusively in **Turso** (`capital_ledgers`, `pending_orders`, `etf_scorecards_master`, `yahoo_daily_prices`, `feature_lineage_audit`, `decision_lineage_audit`, `prod_vs_shadow_master`, `olympic_shootout_master`, `process_continuity`).

---

## 2. Distributed Cloud Topology (Vultr VPS + Prefect 3 vs. Repair Laptop)
1. **Vultr Cloud VPS (`66.42.118.26`) — Live Active Trader & Web Server:**
   - **Prefect 3 Orchestrator (`prefect_pipeline.py serve`)**: Executes scheduled pre-flight checks (`preflight_check.py`), the post-market nightly pipeline (`master_pipeline.py` $\to$ `etf_pipeline.py`), weekend deep-learning trainers, and the hourly Zombie Hunter (`clean_ghosts.py`).
   - **Intraday Sniper (`intraday_tracker.py`)**: Polls live 1-minute bars every 3 minutes during NYSE market hours (`09:30–16:00 EST`), executing VWAP breakouts, momentum shields, and VIX-scaled Take-Profit/Stop-Loss rules, with a `15:55 EST` EOD settlement fallback.
   - **VIX Watchdog (`vix_monitor.py`)**: Continuously tracks CBOE `^VIX` to adjust risk multipliers.
   - **FastAPI Dashboard Server (`server.py` via `ag-uvicorn.service` on Port 80)**: Serves 100% Turso-backed JSON endpoints (`/api/holdings`, `/api/race`, `/api/unified_arena`, `/api/bayesian`, `/api/autopsy`, `/api/trace`).
2. **The Laptop (`C:\Users\AviShemla\AntiGravity`) — Repair & Audit Workstation:**
   - Used for heavy historical backfills, forensic audits, and full 9-script QA verification (`qa_manager.py`).
   - Migration backups are saved to `C:\Users\AviShemla\AG_BCK` for automatic Google Drive synchronization.

---

## 3. The 7-Stage Deterministic Source-to-Target Lineage Architecture
Every historical and live trade across all 8 personas is deterministically traceable from raw market bar to final double-entry ledger balance via `python trace_decision.py --date YYYY-MM-DD --ticker TTTT --persona PPPP` (and `/api/trace`):

1. **Stage 1 — Raw Market Bars (`yahoo_daily_prices`):**
   - Verified daily `Close` and `Volume` for session $T-1$ and $T$ with automatic Tiingo REST failover (`failover_downloader.py`).
2. **Stage 2 — Causal Lead-Lag & Feature Selection (`feature_lineage_audit`):**
   - Single Stocks: Top 3 technical predictors (`all_predictors_df.shift(1)` strictly preventing $T$-day leakage) + causal lag chain (`Lag1..Lag3`) + sector regime (`SEC_REG`, `SEC_MOM`, `AC`, `UPSIDE`).
   - ETFs: 2 Macro + 2 Micro Whale lagged predictors from `*_Hybrid_Screener_Results.csv` and `*_Hybrid_Matrix.csv`.
3. **Stage 3 — Chronological Train/Test Split & Z-Score Scaling (`feature_lineage_audit`):**
   - Strictly isolated training window (`len - 30`) vs. held-out test window (`30` days).
   - Stores exact `raw_feature_values_json`, `train_mean_json` ($X_m$), `train_std_json` ($X_s$), and `z_scored_vector_json` ($Z = (X - X_m)/X_s$), verified to $< 10^{-7}$ error.
4. **Stage 4 — Seeded 2-Chain PyMC SV + Dual-Head MCMC (`oracle_lineage_core.deterministic_mcmc_seed`):**
   - Seeds derived deterministically from `SHA-256("ORACLE_MCMC_V1|{ticker}|{target_date}|{stage}")`.
   - Runs 2 chains (`draws=1000, tune=1000, target_accept=0.90`) to produce posterior $P(\text{UP})$, $\mathbb{E}[R]$, and Stochastic Volatility risk $\sigma_{\text{SV}}$.
5. **Stage 5 — Canonical 8-Persona Gate & Bounded Fractional Kelly (`decision_lineage_audit`):**
   - Bounded payoff ratio $R_{\text{eff}} = \max(1.0, \mathbb{E}[R] / \sigma_{\text{SV}})$ when $\mathbb{E}[R] > 0$ prevents Bayesian shrinkage from zeroing out positive-edge Kelly allocations:
     $$f_{\text{raw}} = \max\left(0, \, P(\text{UP}) - \frac{1 - P(\text{UP})}{R_{\text{eff}}}\right), \quad f_{\text{applied}} = \min\left(\text{MaxCap}, \, f_{\text{raw}} \times k_{\text{persona}} \times m_{\text{VIX}}\right)$$
   - **8 Active Personas (All Initialized at Exactly `$10,000.00` Inception):**
     - **Single Stocks (`MaxCap = 25%`):**
       - `Conservative`: $P(\text{UP}) \ge 0.60$, $\text{Sharpe} \ge 0.12$, $k = 0.25$
       - `Neutral`: $P(\text{UP}) \ge 0.56$, $\text{Sharpe} \ge 0.10$, $k = 0.50$
       - `Dynamic`: $P(\text{UP}) \ge 0.55$, $\text{Sharpe} \ge 0.10$, $k = 0.60$
       - `BallsForBrains`: $P(\text{UP}) \ge 0.53$, $\text{Sharpe} \ge 0.05$, $k = 0.90$
     - **Multi-Sector ETFs (`MaxCap = 25%`):**
       - `ETF_Conservative`: $P(\text{UP}) \ge 0.57$, $\text{Sharpe} \ge 0.05$, $k = 0.25$
       - `ETF_Neutral`: $P(\text{UP}) \ge 0.54$, $\text{Sharpe} \ge 0.03$, $k = 0.50$
       - `ETF_Dynamic`: $P(\text{UP}) \ge 0.53$, $\text{Sharpe} \ge 0.03$, $k = 0.60$
       - `ETF_BallsForBrains`: $P(\text{UP}) \ge 0.51$, $\text{Sharpe} \ge 0.01$, $k = 0.75$
6. **Stage 6 — Virtual Broker Staging (`pending_orders`) & Intraday Sniper (`intraday_tracker.py`):**
   - Converts `applied_kelly` into integer share counts (`units = int(alloc_dollars // close_price)`) and stages `pending_orders` in **Turso**.
   - Intraday Sniper evaluates live 1m VWAP & volume gates during NYSE hours.
7. **Stage 7 — Double-Entry & Inter-Day Ledger Continuity (`capital_ledgers`):**
   - Strictly enforces on every row:
     $$\text{Cash}_t + \sum_{i} \text{Holdings}_{i,t} = \text{Total\_Equity}_t \quad (\text{diff} = \$0.00)$$
     $$\text{Total\_Equity}_t = \text{Total\_Equity}_{t-1} + \sum_{i} \text{Daily\_PnL}_{i,t} \quad (\text{diff} = \$0.00)$$
     $$\text{Daily\_PnL}_{i,t} = \text{Dollars}_{i,t-1} \times \frac{\text{Close}_{i,t} - \text{Close}_{i,t-1}}{\text{Close}_{i,t-1}}$$

---

## 4. The 9-Script Zero-Trust QA Suite (`qa_manager.py`)
Before any `git commit`, `git push`, or executive email dispatch, `qa_manager.py` must pass **9/9 scripts (`100% GREEN`)**:
1. `qa_api_health.py`: Polls all live FastAPI JSON endpoints on Port 80.
2. `qa_auditor.py`: Validates core scorecard bounds and data structures.
3. `qa_dashboard_integrity.py`: Verifies scorecard continuity, cross-system holding sync, and `Prod_vs_Shadow` alignment.
4. `qa_data_alignment.py`: Verifies predictor matrix alignment and NaN-bridging.
5. `qa_data_continuity_per_ticker.py`: Verifies 0 tail-end date gaps and 0 orphaned holdings across VIP tickers.
6. `qa_financial_audit.py`: Audits all 8 personas across 5 checks:
   - Check 1: Cash non-negativity (`Cash >= 0`)
   - Check 2: Double-Entry Identity (`Cash + sum(Holdings) == Total_Equity`)
   - Check 3: Inter-Day Continuity (`Equity[t] == Equity[t-1] + sum(Daily_PnL[t])`)
   - Check 3b: `>5%` Single-Day Equity Spike/Drop Anomaly Audit
   - Check 4: Anti-Flatline Audit across trailing 20 sessions
   - Check 5: `$10,000.00` Inception Baseline Audit across all 8 personas
7. `qa_ledger_balance.py`: Unit-tests Kelly bounds, fractional PnL precision, zero-unit refunds, and division-by-zero traps.
8. `qa_logical_flows.py`: Verifies PyTensor config, array padding, Tiingo failover, train/test isolation, and intraday payload mutation.
9. `qa_task_auditor.py`: Runs `clean_ghosts.py` (Zombie Hunter), verifies schema parity, checks 8-persona `pending_orders` / `capital_ledgers` readiness for today's trading session, and verifies Stock $\to$ ETF `process_continuity` sequencing.
