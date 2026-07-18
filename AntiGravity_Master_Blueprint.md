# 🌌 THE ANTIGRAVITY MASTER BLUEPRINT
**System Reconstruction & Architecture Manual**
*Last Updated: End of June 2026 Phase (MILESTONE ACHIEVED: 5-Day Continuous Clean Run)*

> [!IMPORTANT]
> **To any future AI Agent reading this:** This document is the ultimate fail-safe. If the system has crashed, or if you have lost conversation context, read this document carefully. It contains the exact mathematical logic, architectural flow, and structural purpose of the entire AntiGravity ecosystem. If you need to rebuild the engine, follow this blueprint exactly.

---

## 1. Core Purpose & Philosophy
The **AntiGravity** system is a fully autonomous, predictive mathematical trading engine. It does not rely on simple moving averages or lagging indicators. Instead, it relies on advanced **Bayesian PyMC Regression**, **Stochastic Volatility**, and **Causal Inference** to predict the *probabilistic direction* and *magnitude* of Single Stocks and Thematic ETFs.
It is designed to systematically extract alpha from the market using heavy downside protection (Dynamic VIX Stop-Losses) and mathematically optimal bet sizing (The Kelly Criterion).

---

## 2. The Global Pipeline Flow
The entire system operates on a rigid, hierarchical pipeline. It is fully automated via Windows Task Scheduler.

### 📅 The Schedule
1. **The Heavy ETF Screener:** Runs **Sunday at 1:00 AM**. Scrapes 5,000+ ETFs from the Nasdaq FTP, filters for $50M daily liquidity, and outputs a 35-ETF Master Universe.
2. **The Daily Production Run:** Runs **Tuesday through Saturday at 1:00 AM**. Triggers `run_pipeline.bat` -> `master_pipeline.py`.
3. **The Olympic Marathon:** Runs **Saturday at 2:00 PM**. Executes massive 30-day continuous walk-forward backtests.

### 🔄 The Daily Execution Sequence (`master_pipeline.py`)
When the pipeline wakes up at 1:00 AM, it executes in this exact order:
1. **Data Loading:** Hits Yahoo Finance and FRED for massive matrix array validation.
2. **The Funnels (Screeners):** Discards losers. Extracts Top 15 S&P 500 Stocks and Top 10 Dynamic ETFs based on extreme 30-day Momentum * Volatility.
3. **The Bayesian Engine (PyMC):** The PyTensor graph computes the exact probabilistic chance of the asset going UP tomorrow.
4. **The Virtual Broker:** Settles yesterday's ledger, looks at the new Bayesian probabilities, and calculates new bet sizes using Kelly Sizing.
5. **Reporting:** The Executive Assistant dispatches a rich HTML email to the User via Gmail SMTP.

---

## 3. The Mathematical Brain (PyMC Engines)
The core predictive capability lives in `export_bayesian_scorecard_TNX.py` (Stocks) and `export_etf_scorecard.py` (ETFs).

### 🐳 Dynamic Whale Extraction (ETFs)
The ETF engine is highly intelligent. If given a random ETF (e.g., `XBI`), it natively calls `etf_whale_extractor.py` to instantly reverse-engineer the ETF, pull its Top 5 individual holding "Whales" (e.g., Moderna, Vertex), and predict the ETF's direction based on the fundamental momentum of its underlying whales.

### ⚡ Rust-Compiled Stochastic Volatility (V2 Engine)
The engines use a `GaussianRandomWalk` (Stochastic Volatility) model compiled in Rust (`nutpie` sampler) to predict *tomorrow's* latent volatility. Instead of guessing risk based on the past 30 days, it mathematically projects the exact localized risk of the asset for tomorrow. This latent volatility is directly fed into the Kelly Criterion.

### 🧠 Deep Learning Hybrid Overlays (Shadow AI)
Running directly alongside the rigid Bayesian engines is the **Deep Learning Transformer Pipeline**. This neural network bypasses linear causality entirely, learning pure non-linear alpha from multidimensional price tensors via Self-Attention layers. It is strictly partitioned to prevent timeout crashes:
- **`weekend_dl_trainer.py`**: Executes massive 500-epoch training cycles exclusively on Saturdays to generate `.pt` PyTorch brain weights.
- **`daily_dl_inference.py`**: Uses the pre-trained `.pt` weights to conduct millisecond daily inferences at 1:00 AM without bottlenecking the pipeline.
*(Currently running in "Shadow Mode" to gather validation PnL before going live).*

---

## 4. The Virtual Broker & Risk Management
The trading execution is handled by `virtual_broker.py` and `etf_virtual_broker.py`. The system trades under three distinct risk personas:
1. **Conservative:** Very tight Kelly sizing, low risk tolerance.
2. **Neutral:** The balanced baseline.
3. **BallsForBrains:** Highly aggressive, zero-fear scaling. (Historically performs the best).

### 🛡️ Dynamic VIX Stop-Losses
The Virtual Broker monitors the global `^VIX` (Fear Gauge). If the market enters a flash crash, the Broker dynamically tightens its stop-losses in real-time based on the Persona:
- **VIX < 15 (Calm):** BallsForBrains allows a massive `-6.0%` breathing room intraday.
- **VIX > 25 (Panic):** BallsForBrains radically tightens its stop-loss to a suffocating `-2.0%` to immediately eject and protect capital.

### 💾 Idempotent Ledger Overwrites & Version Tracking
The system is immune to double-buying. If the pipeline crashes midway and re-runs, the Broker reads its own SQLite ledger (`antigravity.db`). If it sees it already traded today, it verifies scorecard integrity and performs a safe mathematical overwrite inside the database without duplicating open orders. 
Furthermore, it actively stamps a `CURRENT_MODEL_VERSION` flag (e.g. `V1.0 - Pure PyMC Bayesian`) onto every ledger row to guarantee a perfect chronological history of which math engine made the trade.

---

## 5. UI & Architecture Monitoring
- **The Dashboard:** Hosted on a custom FastAPI `server.py` backend (`http://theoracle`), displaying a premium, 3D interactive web interface of the daily scorecards and ledgers fetched directly from SQLite.
- **The Visual Map:** The entire system structure is visualized in `Architecture_Map.html`.

### 🗺️ The Architecture Node Dictionary
For deep crash recovery, here is the exact purpose, input, output, and schedule of every core node in the system:

- **SSOT_DB (`antigravity.db`)** | Purpose: The Single Source of Truth SQLite core. Eliminates race conditions and fully decouples the Math Models, Execution Engines, and UI from fragile CSV files. | Input: Orders & Ledgers | Output: Verified States | Schedule: Always On
- **MASTER (`master_pipeline.py`)** | Purpose: Central nervous system commanding automated daily execution. | Input: Windows Task Scheduler | Output: Orchestrated Scripts | Schedule: Daily at 1:00 AM
- **FAILOVER (`failover_downloader.py`)** | Purpose: Self-healing data fetcher. Uses exponential backoff and alternate Tiingo API to bypass yfinance failures. | Input: Tickers | Output: CSV Data | Schedule: On-Demand
- **DATA_LOADER (`data_loader.py`)** | Purpose: Flawless matrix extraction. Pre-slices history and rigidly enforces no duplicate forward-dates pollute MCMC chains. | Input: Raw Price Data | Output: Clean Multi-Lag Arrays | Schedule: Pre-inference
- **STOCK_PYMC (`export_bayesian_scorecard_TNX.py`)** | Purpose: Project Apollo causality engine. Correlates global macro features into Rust NUTS sampler. | Input: Top 15 Tickers + Macro | Output: P(UP) Predictions | Schedule: Daily
- **DEEP_TRAINER (`weekend_dl_trainer.py`)** | Purpose: Massive multi-dimensional Self-Attention Neural Network training framework. | Input: 60-day historical tensors | Output: `.pt` PyTorch weights | Schedule: Weekend
- **DEEP_INFERENCE (`daily_dl_inference.py`)** | Purpose: Rapid millisecond Shadow Engine generating non-linear alpha predictions. | Input: `.pt` weights + daily tensors | Output: Shadow Scorecard | Schedule: Daily
- **STOCK_BROKER (`virtual_broker.py`)** | Purpose: Calculates mathematical capital allocations based on scorecards. | Input: Predictive Scorecards | Output: Pending SQLite Orders | Schedule: Daily
- **INTRADAY_SNIPER (`intraday_tracker.py`)** | Purpose: Polls live market prices. Executes intended target staging only when momentum is optimal. | Input: Pending SQLite Orders | Output: Executed SQLite Ledger | Schedule: Intraday
- **BACKEND (`server.py`)** | Purpose: FastAPI REST Server bridging Python SQLite data to frontend web application. | Input: SQLite Ledgers & Scorecards | Output: JSON Endpoints | Schedule: Always Online

---

## 6. 🚨 System Recovery Protocol (If Everything Crashes)
If the AI Agent is deployed into a totally broken environment, execute the following steps in exact order to restore AntiGravity:

1. **Verify MCP Integrity:** Check if `.vscode/mcp_config.json` is corrupted. If tool calls are failing, it is likely a syntax error in the MCP configuration.
2. **Verify Python Environment:** Ensure all PyMC, PyTensor, and `nutpie` dependencies are properly compiled. The `engine_config.py` explicitly forces PyTensor C-Graph settings (`cxx=`).
7. **Audit API Limits:** If Yahoo Finance throws a `429 RateLimitError`, ensure `failover_downloader.py` is correctly intercepting the crash and routing through the **Tiingo Institutional API** fallback. The system relies on the `api_keys.json` vault for the Tiingo token. If the Tiingo failover is exhausted, ensure `ETF_Universe_Screener.py` is utilizing its 10-second chunking cooldown. You must wait 60 minutes for Yahoo's ban to lift.
4. **Sanity Check Execution:** Run `python qa_logical_flows.py` to ensure the mathematical funnels are passing correctly.
5. **Bypass Lock:** Run `python virtual_broker.py` directly to see if the idempotent ledger is successfully overwriting without corrupting the cash balance.
6. **Consult the Master Log:** Check the `master_pipeline_log.txt` for the exact traceback of the nightly failure.

*End of Blueprint.*

---

## 7. 🗂️ Global Process Registry Table

| Process Name | File Name | Code / Primary Function |
| :--- | :--- | :--- |
| **Master Orchestrator** | `master_pipeline.py` | Central nervous system. Executes all daily scripts in strict sequential order. |
| **ETF Universe Screener** | `ETF_Universe_Screener.py` | Scrapes 5,000+ Nasdaq ETFs, applies $50M liquidity firewall, saves Top 35. |
| **Data Normalization** | `data_loader.py` | Fetches YFinance & FRED macro data, handles lagging, and cleans matrices. |
| **Bayesian Engine (Stocks)**| `export_bayesian_scorecard_TNX.py` | Compiles Rust SV engine and PyTensor graphs to predict Single Stock P(UP). |
| **Bayesian Engine (ETFs)** | `export_etf_scorecard.py` | Evaluates Thematic ETFs by analyzing their underlying "Whale" fundamentals. |
| **Deep Learning Trainer** | `weekend_dl_trainer.py` | Heavy weekend Transformer network training loop (500 Epochs -> `.pt` weights). |
| **Deep Learning Inference** | `daily_dl_inference.py` | Lightning-fast daily shadow predictions using the loaded `.pt` weights. |
| **Virtual Broker (Stocks)** | `virtual_broker.py` | Calculates Kelly Sizing allocations for stocks and stores pending orders. |
| **Virtual Broker (ETFs)** | `etf_virtual_broker.py` | Calculates Kelly Sizing allocations for ETFs and stores pending orders. |
| **Intraday Sniper** | `intraday_tracker.py` | Polls live market, executes staged orders, manages stop-loss, and commits DB ledgers. |
| **Data Failover** | `failover_downloader.py` | Defensive routing to Tiingo Institutional API if Yahoo Finance issues an IP ban. |
| **Dashboard Backend** | `server.py` | FastAPI application serving JSON data securely to the frontend. |
| **Command Center UI** | `dashboard.py` | Streamlit interactive web interface that visualizes ledgers, models, and PnL. |

---
### ??? June 13, 2026 Update: Deep Learning Shadow Engine & SQLite Hardening
- **Architecture Upgrades**: Successfully integrated the PyTorch LSTM & Transformer Shadow models alongside the PyMC engine. The new daily_dl_inference.py autonomously generates unified Single Stock and ETF Macro scorecards.
- **Data Continuity**: Fully migrated all ledgers away from volatile Excel/OneDrive dependencies into the secure ntigravity.db SQLite schema.
- **QA Verifications**: Hardened irtual_broker.py against fatal YFinance date mismatches, fixed tz-naive pandas crashes in intraday_tracker.py, and verified the Marathon engine's dynamic date_range catch-up mechanism to prevent redundant simulations.
- **Status**: 100% Green. Portfolios balanced. FastAPI Web Dashboard active.

---
### 🛡️ June 16, 2026 Update: Phase 1 Macro Indicators & Master Watchdog
- **Architecture Upgrades**: Deployed `master_watchdog.py` as an always-on fail-safe replacing Windows Task Scheduler. Engineered `sector_gravity.py` to mathematically map ETFs and violently abort limit orders inside bleeding sectors. Injected the 10-Year Treasury Yield (`^TNX`) into the PyMC input matrix to dynamically dampen risk during Yield Curve shocks.
# 🌌 THE ANTIGRAVITY MASTER BLUEPRINT
**System Reconstruction & Architecture Manual**
*Last Updated: End of June 2026 Phase (MILESTONE ACHIEVED: 5-Day Continuous Clean Run)*

> [!IMPORTANT]
> **To any future AI Agent reading this:** This document is the ultimate fail-safe. If the system has crashed, or if you have lost conversation context, read this document carefully. It contains the exact mathematical logic, architectural flow, and structural purpose of the entire AntiGravity ecosystem. If you need to rebuild the engine, follow this blueprint exactly.

---

## 1. Core Purpose & Philosophy
The **AntiGravity** system is a fully autonomous, predictive mathematical trading engine. It does not rely on simple moving averages or lagging indicators. Instead, it relies on advanced **Bayesian PyMC Regression**, **Stochastic Volatility**, and **Causal Inference** to predict the *probabilistic direction* and *magnitude* of Single Stocks and Thematic ETFs.
It is designed to systematically extract alpha from the market using heavy downside protection (Dynamic VIX Stop-Losses) and mathematically optimal bet sizing (The Kelly Criterion).

---

## 2. The Global Pipeline Flow
The entire system operates on a rigid, hierarchical pipeline. It is fully automated via Windows Task Scheduler.

### 📅 The Schedule
1. **The Heavy ETF Screener:** Runs **Sunday at 1:00 AM**. Scrapes 5,000+ ETFs from the Nasdaq FTP, filters for $50M daily liquidity, and outputs a 35-ETF Master Universe.
2. **The Daily Production Run:** Runs **Tuesday through Saturday at 1:00 AM**. Triggers `run_pipeline.bat` -> `master_pipeline.py`.
3. **The Marathon (Continuous 1-Day):** Runs dynamically within the daily pipeline. Executes a continuous 1-day predictive walk-forward step to avoid massive 30-day weekend API overloads.

### 🔄 The Daily Execution Sequence (`master_pipeline.py`)
When the pipeline wakes up at 1:00 AM, it executes in this exact order:
0. **OS CPU Priority Elevation:** The Python process immediately requests `HIGH_PRIORITY_CLASS` from the Windows kernel. This mathematically guarantees that the core live-trading logic (Steps 1-7) never gets starved of CPU/RAM by the 18-hour background PyMC Shootout spawned at Step 8 (which runs at `BELOW_NORMAL_PRIORITY_CLASS`).
1. **Data Loading & NaN Bridging:** Hits Yahoo Finance and FRED for massive matrix array validation. A robust "NaN-Bridge" (`.ffill()`) actively patrols the data streams to mathematically forward-fill any structurally missing dates (e.g. Juneteenth) without crashing the downstream algorithms.
2. **The Funnels (Screeners):** Discards losers. Extracts Top 15 S&P 500 Stocks and Top 10 Dynamic ETFs based on extreme 30-day Momentum * Volatility.
3. **The Bayesian Engine (PyMC):** The PyTensor graph computes the exact probabilistic chance of the asset going UP tomorrow.
4. **The Virtual Broker:** Settles yesterday's ledger, looks at the new Bayesian probabilities, and calculates new bet sizes using Kelly Sizing.
5. **Reporting:** The Executive Assistant dispatches a rich HTML email to the User via Gmail SMTP.

---

## 3. The Mathematical Brain (PyMC Engines)
The core predictive capability lives in `export_bayesian_scorecard_TNX.py` (Stocks) and `export_etf_scorecard.py` (ETFs).

### 🐳 Dynamic Whale Extraction (ETFs)
The ETF engine is highly intelligent. If given a random ETF (e.g., `XBI`), it natively calls `etf_whale_extractor.py` to instantly reverse-engineer the ETF, pull its Top 5 individual holding "Whales" (e.g., Moderna, Vertex), and predict the ETF's direction based on the fundamental momentum of its underlying whales.

### ⚡ Rust-Compiled Stochastic Volatility (V2 Engine)
The engines use a `GaussianRandomWalk` (Stochastic Volatility) model compiled in Rust (`nutpie` sampler) to predict *tomorrow's* latent volatility. Instead of guessing risk based on the past 30 days, it mathematically projects the exact localized risk of the asset for tomorrow. This latent volatility is directly fed into the Kelly Criterion.

### 🧠 Deep Learning Hybrid Overlays (Shadow AI)
Running directly alongside the rigid Bayesian engines is the **Deep Learning Transformer Pipeline**. This neural network bypasses linear causality entirely, learning pure non-linear alpha from multidimensional price tensors via Self-Attention layers. It is strictly partitioned to prevent timeout crashes:
- **`weekend_dl_trainer.py`**: Executes massive 500-epoch training cycles exclusively on Saturdays to generate `.pt` PyTorch brain weights.
- **`daily_dl_inference.py`**: Uses the pre-trained `.pt` weights to conduct millisecond daily inferences at 1:00 AM without bottlenecking the pipeline.
*(Currently running in "Shadow Mode" to gather validation PnL before going live).*

---

## 4. The Virtual Broker & Risk Management
The trading execution is handled by `virtual_broker.py` and `etf_virtual_broker.py`. The system trades under three distinct risk personas:
1. **Conservative:** Very tight Kelly sizing, low risk tolerance.
2. **Neutral:** The balanced baseline.
3. **BallsForBrains:** Highly aggressive, zero-fear scaling. (Historically performs the best).

### 🛡️ Dynamic VIX Stop-Losses
The Virtual Broker monitors the global `^VIX` (Fear Gauge). If the market enters a flash crash, the Broker dynamically tightens its stop-losses in real-time based on the Persona:
- **VIX < 15 (Calm):** BallsForBrains allows a massive `-6.0%` breathing room intraday.
- **VIX > 25 (Panic):** BallsForBrains radically tightens its stop-loss to a suffocating `-2.0%` to immediately eject and protect capital.

### 💾 Idempotent Ledger Overwrites & Version Tracking
The system is immune to double-buying. If the pipeline crashes midway and re-runs, the Broker reads its own SQLite ledger (`antigravity.db`). If it sees it already traded today, it verifies scorecard integrity and performs a safe mathematical overwrite inside the database without duplicating open orders. 
Furthermore, it actively stamps a `CURRENT_MODEL_VERSION` flag (e.g. `V1.0 - Pure PyMC Bayesian`) onto every ledger row to guarantee a perfect chronological history of which math engine made the trade.

---

## 5. UI & Auto-Healing Architecture
- **Zero-Touch Live Dashboard:** Hosted on a custom FastAPI `server.py` backend (`http://theoracle`), displaying a premium, 3D interactive web interface. The dashboard features a **3-Layer Zero-Touch Architecture**:
  1. **Backend Hot-Reloading:** The `master_watchdog.py` runs Uvicorn with `--reload` to instantly ingest Python patches.
  2. **Aggressive Frontend Cache-Busting:** `index.html` loads the Javascript payload with dynamic timestamps (`Date.now()`) to physically bypass stale browser caches.
  3. **Live Auto-Polling:** The frontend Javascript uses a 60-second polling loop to automatically render pre-market `pending_orders` and natively transition them into live execution tracking without user intervention.
- **Agentic Auto-Healing Watchdog:** Instead of passive QA email alerts, a scheduled AI Cron Job wakes up the Agent daily at 05:30 AM to proactively run `system_qa_auditor.py`. If errors are detected, the Agent autonomously writes code fixes, patches the database, and restarts the pipeline to guarantee a 100% green state before market open.
- **The Visual Map:** The entire system structure is visualized in `Architecture_Map.html`.

### 🗺️ The Architecture Node Dictionary
For deep crash recovery, here is the exact purpose, input, output, and schedule of every core node in the system:

- **SSOT_DB (`antigravity.db`)** | Purpose: The Single Source of Truth SQLite core. Eliminates race conditions and fully decouples the Math Models, Execution Engines, and UI from fragile CSV files. | Input: Orders & Ledgers | Output: Verified States | Schedule: Always On
- **MASTER (`master_pipeline.py`)** | Purpose: Central nervous system commanding automated daily execution. | Input: Windows Task Scheduler | Output: Orchestrated Scripts | Schedule: Daily at 1:00 AM
- **WATCHDOG (`master_watchdog.py`)** | Purpose: Continuous background daemon that ensures system health. Automatically resurrects dead Uvicorn servers, hunts zombie processes, and triggers API health audits. | Input: Process Tree | Output: Alive Daemons | Schedule: Background Infinite Loop
- **FAILOVER (`failover_downloader.py`)** | Purpose: Self-healing data fetcher. Uses exponential backoff and alternate Tiingo API to bypass yfinance failures. | Input: Tickers | Output: CSV Data | Schedule: On-Demand
- **DATA_LOADER (`data_loader.py`)** | Purpose: Flawless matrix extraction. Pre-slices history and rigidly enforces no duplicate forward-dates pollute MCMC chains. | Input: Raw Price Data | Output: Clean Multi-Lag Arrays | Schedule: Pre-inference
- **STOCK_PYMC (`export_bayesian_scorecard_TNX.py`)** | Purpose: Project Apollo causality engine. Correlates global macro features into Rust NUTS sampler. | Input: Top 15 Tickers + Macro | Output: P(UP) Predictions | Schedule: Daily
- **DEEP_TRAINER (`weekend_dl_trainer.py`)** | Purpose: Massive multi-dimensional Self-Attention Neural Network training framework. | Input: 60-day historical tensors | Output: `.pt` PyTorch weights | Schedule: Weekend
- **DEEP_INFERENCE (`daily_dl_inference.py`)** | Purpose: Rapid millisecond Shadow Engine generating non-linear alpha predictions. | Input: `.pt` weights + daily tensors | Output: Shadow Scorecard | Schedule: Daily
- **STOCK_BROKER (`virtual_broker.py`)** | Purpose: Calculates mathematical capital allocations based on scorecards. | Input: Predictive Scorecards | Output: Pending SQLite Orders | Schedule: Daily
- **INTRADAY_SNIPER (`intraday_tracker.py`)** | Purpose: Constantly polls live market ask/bid prices during market hours. Executes intended target staging only when momentum is optimal. | Input: Pending SQLite Orders | Output: Executed SQLite Ledger | Schedule: Intraday
- **BACKEND (`server.py`)** | Purpose: FastAPI REST Server bridging Python SQLite data to frontend web application. Endpoints include /api/race_data, /api/prod_shadow, and /api/olympic. | Input: SQLite Ledgers & Scorecards | Output: JSON Endpoints | Schedule: Managed by Watchdog
- **QA_UI_AGENT (`qa_api_health.py`)** | Purpose: Automated watchdog script that acts as an invisible user clicking through the dashboard every 15 minutes. It strictly queries local API JSON payloads to verify structural math integrity. If a backend tab crashes, it logs an alert to `master_watchdog.log` without aggressively mutating state. | Input: REST API Endpoints | Output: Health Validations | Schedule: Every 15 mins

---

## 6. 🚨 System Recovery Protocol (If Everything Crashes)
If the AI Agent is deployed into a totally broken environment, execute the following steps in exact order to restore AntiGravity:

1. **Verify MCP Integrity:** Check if `.vscode/mcp_config.json` is corrupted. If tool calls are failing, it is likely a syntax error in the MCP configuration.
2. **Verify Python Environment:** Ensure all PyMC, PyTensor, and `nutpie` dependencies are properly compiled. The `engine_config.py` explicitly forces PyTensor C-Graph settings (`cxx=`).
7. **Audit API Limits:** If Yahoo Finance throws a `429 RateLimitError`, ensure `failover_downloader.py` is correctly intercepting the crash and routing through the **Tiingo Institutional API** fallback. The system relies on the `api_keys.json` vault for the Tiingo token. If the Tiingo failover is exhausted, ensure `ETF_Universe_Screener.py` is utilizing its 10-second chunking cooldown. You must wait 60 minutes for Yahoo's ban to lift.
4. **Sanity Check Execution:** Run `python qa_logical_flows.py` to ensure the mathematical funnels are passing correctly.
5. **Bypass Lock:** Run `python virtual_broker.py` directly to see if the idempotent ledger is successfully overwriting without corrupting the cash balance.
6. **Consult the Master Log:** Check the `master_pipeline_log.txt` for the exact traceback of the nightly failure.

*End of Blueprint.*

---

## 7. 🗂️ Global Process Registry Table

| Process Name | File Name | Code / Primary Function |
| :--- | :--- | :--- |
| **Master Orchestrator** | `master_pipeline.py` | Central nervous system. Executes all daily scripts in strict sequential order. |
| **ETF Universe Screener** | `ETF_Universe_Screener.py` | Scrapes 5,000+ Nasdaq ETFs, applies $50M liquidity firewall, saves Top 35. |
| **Data Normalization** | `data_loader.py` | Fetches YFinance & FRED macro data, handles lagging, and cleans matrices. |
| **Bayesian Engine (Stocks)**| `export_bayesian_scorecard_TNX.py` | Compiles Rust SV engine and PyTensor graphs to predict Single Stock P(UP). |
| **Bayesian Engine (ETFs)** | `export_etf_scorecard.py` | Evaluates Thematic ETFs by analyzing their underlying "Whale" fundamentals. |
| **Deep Learning Trainer** | `weekend_dl_trainer.py` | Heavy weekend Transformer network training loop (500 Epochs -> `.pt` weights). |
| **Deep Learning Inference** | `daily_dl_inference.py` | Lightning-fast daily shadow predictions using the loaded `.pt` weights. |
| **Virtual Broker (Stocks)** | `virtual_broker.py` | Calculates Kelly Sizing allocations for stocks and stores pending orders. |
| **Virtual Broker (ETFs)** | `etf_virtual_broker.py` | Calculates Kelly Sizing allocations for ETFs and stores pending orders. |
| **Intraday Sniper** | `intraday_tracker.py` | Polls live market, executes staged orders, manages stop-loss, and commits DB ledgers. |
| **Data Failover** | `failover_downloader.py` | Defensive routing to Tiingo Institutional API if Yahoo Finance issues an IP ban. |
| **Dashboard Backend** | `server.py` | FastAPI application serving JSON data securely to the frontend. |
| **Command Center UI** | `dashboard.py` | Streamlit interactive web interface that visualizes ledgers, models, and PnL. |

---
### ??? June 13, 2026 Update: Deep Learning Shadow Engine & SQLite Hardening
- **Architecture Upgrades**: Successfully integrated the PyTorch LSTM & Transformer Shadow models alongside the PyMC engine. The new daily_dl_inference.py autonomously generates unified Single Stock and ETF Macro scorecards.
- **Data Continuity**: Fully migrated all ledgers away from volatile Excel/OneDrive dependencies into the secure  ntigravity.db SQLite schema.
- **QA Verifications**: Hardened  irtual_broker.py against fatal YFinance date mismatches, fixed tz-naive pandas crashes in intraday_tracker.py, and verified the Marathon engine's dynamic  date_range catch-up mechanism to prevent redundant simulations.
- **Status**: 100% Green. Portfolios balanced. FastAPI Web Dashboard active.

---
### 🛡️ June 16, 2026 Update: Phase 1 Macro Indicators & Master Watchdog
- **Architecture Upgrades**: Deployed `master_watchdog.py` as an always-on fail-safe replacing Windows Task Scheduler. Engineered `sector_gravity.py` to mathematically map ETFs and violently abort limit orders inside bleeding sectors. Injected the 10-Year Treasury Yield (`^TNX`) into the PyMC input matrix to dynamically dampen risk during Yield Curve shocks.
- **Execution Engine**: Deployed the `intraday_tracker.py` VWAP Sniper. It actively shields execution from morning volatility and uses VIX/Volume Gating to abandon highly volatile trades.
- **Data Continuity**: Merged the fragmented Marathon Shootout files into a single, compounded `Olympic_Shootout_Results_MASTER.csv` ledger for permanent all-time performance tracking.
- **Status**: QA `pre_flight_check.py` confirmed 100% Green system integrity.

---
### ?? June 16, 2026 Update (Late Morning): PyMC Shape Patch & Execution Routing
- **Architecture Upgrades**: Re-engineered the Bayesian stochastic tensor graphs in all three export_bayesian_scorecard.py, export_etf_scorecard.py, and export_bayesian_scorecard_TNX.py engines. Replaced static dependent variable arrays with pm.Data mutable containers, permanently eliminating the PyTensor shape mismatch crashes caused by dynamic feature lengths (like the Yield Curve).

## 5. Security & System Directives
1. **Holding Protection Auto-Healer:** Any mathematical model failure (e.g. PyMC shape mismatch, missing data) instantly aborts the specific trade, logs the failure, and **QUARANTINES** the holding to freeze it. The system must NEVER liquidate a quarantined asset.
2. **Email Communications Directive:** The system must strictly ONLY send emails, alerts, and Executive Briefs to the personal Gmail address (`avi.shemla@gmail.com`). NEVER send or CC emails to the Mobideo work email address under any circumstances.
3. **Execution Safety Limits:** No persona may exceed 10.0% capital allocation per single stock to prevent catastrophic drawdowns.

- **Execution Routing**: Rewrote daily_pipeline.py to ensure it explicitly triggers the ETF pipeline, the executive_brief.py global dashboard, and the un_backtests.py Marathon simulator consecutively. Restructured the Championship email to pull dynamic data from Olympic_Shootout_Results_MASTER.csv.
- **Status**: QA completed without crashes. Fully synchronized.

