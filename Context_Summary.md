# AntiGravity Project Context & Evolution Summary (`Context_Summary.md`)
*Last Updated: October 30, 2026 (`v2.5-Deterministic-Lineage`)*

> **🔴 MANDATORY STARTUP PROTOCOL 🔴**
> Every time a new session starts:
> 1. Read `.agents/AGENTS.md`, `.agents/skills/anti_gravity_prime_directives/SKILL.md`, `SYSTEM_STATE.md`, and `roadmap.md`.
> 2. Execute `qa_manager.py` or inspect live **Turso** and **Vultr** (`66.42.118.26`) state before answering any system status question.

---

## 1. System Evolution: From Research Notebooks to `v2.5-Deterministic-Lineage`
1. **Phases 1–11 (Foundational Quantitative Research):**
   - Evaluated linear multi-lag regressions, stepwise regressions, Bayesian Ridge, and standard BSTS models across S&P 500 and Nasdaq datasets. Proved that unregularized linear models overfit in-sample noise and require Bayesian shrinkage + latent volatility modeling.
2. **Phases 12–13 (Autonomous Pipeline, Failover & Intraday VWAP Sniper):**
   - Built `failover_downloader.py` (Yahoo Finance $\to$ Tiingo REST API failover), `virtual_broker.py`, `etf_virtual_broker.py`, and `intraday_tracker.py` (1m VWAP breakout, Momentum Shield on pending sells, and VIX-scaled Take-Profit / Stop-Loss rules).
3. **Phase 14 (100% Turso Cloud SSOT & Vultr + Prefect 3 Migration):**
   - Migrated all production tables (`capital_ledgers`, `pending_orders`, `etf_scorecards_master`, `yahoo_daily_prices`, `prod_vs_shadow_master`, `olympic_shootout_master`, `process_continuity`) to **Turso**.
   - Migrated orchestration to **Prefect 3** (`prefect_pipeline.py serve`) and `systemd` / background daemons on **Vultr** (`66.42.118.26`).
4. **Phase 15 (`v2.5-Deterministic-Lineage` — October 30, 2026):**
   - **Canonical Lineage Core (`oracle_lineage_core.py`):** Implemented SHA-256 deterministic MCMC seeding (`SV` and `MAIN` stages, 2 chains, 1000 draws, 1000 tune), bounded fractional Kelly sizing ($R_{\text{eff}} = \max(1.0, \mathbb{E}[R]/\sigma_{\text{SV}})$ when $\mathbb{E}[R] > 0$), and calibrated 8-persona Sharpe/probability thresholds.
   - **7-Stage Deterministic Traceability (`trace_decision.py` & `/api/trace`):** Populated `feature_lineage_audit` and `decision_lineage_audit` across all active Stock and ETF tickers (`2026-08-21`..`2026-10-30`) so every prediction and realized dollar PnL is verifiable bit-for-bit.
   - **`$10,000.00`-Inception Full Ledger Reconciliation & 9-Script QA Hardening (`qa_financial_audit.py`):** Reconciled all `695+` ledger rows from exact `$10,000.00` inception using verified single-day market returns, purged legacy duplicate model keys in `prod_vs_shadow_master`, and added Check 3b (`>5%` single-day spike/drop anomaly detector), Check 4 (Anti-Flatline), and Check 5 (`$10,000.00` inception baseline) to `qa_financial_audit.py`.
