# AntiGravity Project Roadmap & Status

## 🎯 Current Active System Directives (Phase 1 Operations)

- <span style="color: #2ECC40; font-weight: bold;">[ACTIVE]</span> **Strict 100% Database SSOT & Query Backing (Turso DB):** ABSOLUTELY NO CSV or Excel files allowed as data sources or fallbacks! All status reports, pending orders, holdings, model history, and trade recommendations MUST be back-tested and queried directly from live Turso DB tables before answering. Never guess or rely on local array memory.
- <span style="color: #2ECC40; font-weight: bold;">[ACTIVE]</span> **Zero Local File Data Source:** No local processing or local CSV/Excel files are to be used as data sources. Database tables are the sole authoritative source of truth across all environments.
- <span style="color: #2ECC40; font-weight: bold;">[ACTIVE]</span> **Mandatory Playwright Visual Inspection QA:** Every dashboard status report or UI update must be visually confirmed using `capture_all_web_tabs.py` Playwright rendering across all live Web Dashboard tabs (`http://66.42.118.26`).
- <span style="color: #2ECC40; font-weight: bold;">[ACTIVE]</span> **Intraday Sniper Daemon Guarding:** `ag-sniper.service` daemon actively evaluating, protecting, and executing staged pending orders across all 8 personas live on Vultr.

## ⏳ Future Directions (Phase 2 Architecture)

1. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **ETF Dynamic Whale Prior (Production Rollout):** The POC math proved that injecting live S&P500 fundamental aggregates into the ETF PyMC engine significantly stabilizes the NUTS sampler. This needs to be fully integrated into `export_etf_scorecard.py` to upgrade the live ETF pipeline.
2. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **Neural Failure Pattern Analytics & Safety Auditing:** Apply deep learning to reverse-engineer "MISSES." Specifically, track when safety mechanisms (VIX stops, VWAP limits, Kelly fractions) override a correct PyMC prediction and *cause* a miss. Use this data to assign dynamic weights to safety conditions.
3. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **Regime-Switching Meta-Model (Traffic Cop):** Develop a master overarching model (Random Forest / XGBoost) that does not predict stocks, but dynamically routes 100% of capital daily between Prod (PyMC), Shadow A (Transformer), or Shadow B (LSTM) based on macro regime classification (VIX, TNX, Breadth).
4. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **Intraday Sniper WebSockets & ATR:** Rip out `yfinance` 1-minute polling for live trade execution. Integrate a robust WebSocket feed (Polygon.io/Alpaca) for millisecond latency, and replace static VWAP multipliers with dynamic Average True Range (ATR) based trailing stops.
5. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **Institutional Fundamentals API:** Move all fundamental and SEC-filing data extraction away from Yahoo Finance web scraping to a guaranteed structured JSON provider like Financial Modeling Prep (FMP) or AlphaVantage to eliminate silent data drops.
6. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **Hierarchical AI (Deep Learning Priors):** Mathematically fuse the architectures by injecting the Transformer's output directly into the PyMC engine as the `mu` prior, rather than just running them as side-by-side competitors.
7. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **CRITICAL DECISION (End of Aug):** After the weekend runs of the Olympic Championship, evaluate the ongoing marathon data. If EL_CAP or EL_VOLTI has mathematically crushed the static VIP list, definitively decide whether to build the Dynamic EL_CAP Funnel for the live Production Pipeline.
5. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **Monday Damping Factor:** Automatically tighten the Kelly fraction by 50% specifically for Monday executions to mitigate the "Weekend Effect" risk seen in the Autopsy logs.
6. <span style="color: #FF851B; font-weight: bold;">[PENDING]</span> **Real-World Execution:** Connect the cloud-hosted system to a live brokerage API for real-world automated trading execution.

---

## 📝 Notes & Investigations
- **Stop-Loss Mechanics:** Investigate and tighten the intraday Stop-Loss thresholds (specifically the 10% ETF stop-loss mechanic) to ensure the Intraday Sniper executes flawlessly and protects capital during sudden market gaps or when background processes hang.
