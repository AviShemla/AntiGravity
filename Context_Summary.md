# AntiGravity Project Context & Startup Protocols

> **🔴 MANDATORY STARTUP PROTOCOL 🔴**
> The USER requires that *every time* a new conversation/session starts, you must immediately do two things:
> 1. Read `roadmap.md` and *cross-reference it with the actual Python codebase* to ensure it hasn't fallen out of sync. Update it if necessary.
> 2. Present the beautifully updated and accurate list of `[PENDING]` and `[FUTURE]` items to the user so they can plan their day.

## Project Objective
Identify predictive relationships between stock performances by analyzing the NASDAQ dataset. The goal is to determine if the daily performance (returns or volume-adjusted returns) of a stock (or combination of stocks) can predict the future performance of a "champion" stock (primarily `GOOG`, but also `TSLA` and `LIN`).

## Key Discoveries & Conclusions
*   **Market Efficiency:** The market for major stocks like GOOG, TSLA, and LIN is extremely efficient. The predictive power of prior days' returns is negligible out-of-sample.
*   **Overfitting Danger:** Traditional Stepwise Regression models often found combinations of stocks that *appeared* highly predictive in historical data ($R^2 \approx 6\%$), but they completely collapsed in out-of-sample testing (negative $R^2$), proving they were just memorizing random noise.
*   **The Bayesian Solution:** The PyMC Labs Bayesian Workflow, which uses priors to prevent overfitting (shrinkage), successfully avoided this trap. It consistently identified that true out-of-sample predictability is practically zero.
*   **Advanced Features:** Complex features like 3-day Moving Averages (MA3), 3-stock Combinations (~2 million pairs tested), and Volume-Adjusted Returns failed to uncover any hidden predictive signals that could beat the random noise.

## Scripts & Methodologies Developed

### 1. Data Preparation (`combine_csvs.py`)
Combined 12 sector-specific CSV files into a unified dataset (`Nasdaq_Data_All_Sectors_Combined.csv`) with a new `Sector` identifier.

### 2. Initial Linear Analysis
*   `calculate_lagged_r2.py` / `calculate_lagged_r2_returns.py`: Found that while stock *prices* correlate due to long-term trends, daily *returns* have near-zero correlation.
*   `analyze_goog_lags.py` / `analyze_sector_champions.py`: Ran multi-lag (1-5 days) linear R2 analysis for single stocks. Found max predictability was < 2%.

### 3. Stepwise Regression (`stepwise_regression_goog.py`, `test_regression_model.py`)
Attempted to combine multiple predictors using a p-value threshold. Found a 10-stock model that explained 6% of variance in training but had a negative R2 in testing (classic overfitting).

### 4. Bayesian Ridge Regression (`bayesian_regression_goog.py`, `bayesian_multilag_analysis.py`)
Applied Bayesian Ridge to automatically shrink non-predictive weights. Confirmed that the training signal was actually near zero, resulting in a more honest (though still slightly negative) test R2.

### 5. PyMC Labs Bayesian Workflow (`pymc_workflow_goog.py`)
Implemented a full, principled Bayesian workflow:
1.  **Prior Predictive Checks:** Ensures priors are reasonable.
2.  **MCMC Sampling:** Used NUTS (No-U-Turn Sampler) via PyMC to find posterior distributions.
3.  **Posterior Predictive Checks:** Validated model simulations.
4.  **Result:** Confirmed the 94% HDI for all predictor weights included exactly zero.

### 6. PyMC Multi-Lag Workflow (`pymc_multilag_workflow.py`)
Automated the PyMC workflow across 6 scenarios:
*   Daily Returns (Lag 1, 2, 3)
*   MA3 Returns (Lag 1, 2, 3)
*   *Result:* Out-of-sample R2 remained negative or near zero.

### 7. PyMC Combinations Workflow (`pymc_combinations_workflow.py`)
*   **Feature:** Built a highly optimized Numpy matrix-multiplication algorithm to search all ~1.95 million unique 3-stock combinations.
*   **Execution:** Found the top 5 historical combinations and fed their averages into the PyMC workflow.
*   **Result:** Still yielded negative out-of-sample R2, proving that even "perfect" historical combinations fail out-of-sample.

### 8. PyMC Volume-Adjusted Workflow (`pymc_volume_workflow.py`)
*   **Feature:** Multiplied daily returns by "Relative Volume" (Today's Volume / 20-day Average Volume) to amplify high-conviction moves.
*   **Result:** Volume spikes increased noise in the short term (Lag 1). Longer lags (MA3 Lag 2/3) showed a tiny positive R2 (~0.2%), but not enough to be statistically significant.

### 9. PyMC Technical Indicators & Volatility-Adjusted Workflow (`pymc_wmt_technical_workflow.py`, `pymc_tsco_technical_workflow.py`)
*   **Feature:** Shifted targets from GOOG to WMT and TSCO. Replaced traditional returns with volatility-adjusted returns (Return / STDEV_5d). Incorporated 14-day RSI and ADX technical indicators.
*   **Execution:** Tested over both the original NASDAQ dataset (manual indicator calculation) and a newly introduced S&P 500 dataset (`SP500_Clean_Advanced_Analysis.csv`) which contained pre-calculated indicators.
*   **Result:** 
    *   Initially found a spurious +5% out-of-sample $R^2$ for WMT on the NASDAQ dataset at Lag 1. 
    *   However, when WMT was tested against the broader S&P 500 dataset, the signal vanished (+0.13%). 
    *   Testing TSCO across both datasets yielded heavily negative $R^2$ scores across all lags. 
    *   **Conclusion:** The initial 5% signal was anomalous. The robust Bayesian shrinkage confirmed that even complex technical indicators and volatility normalization fail to provide a consistent predictive edge out-of-sample due to market efficiency.

### 10. PyMC Volatility Prediction Workflow (`pymc_jpm_volatility_workflow.py`)
*   **Feature:** Shifted from predicting directional returns to predicting **Volatility Magnitude (Absolute Returns)**. The hypothesis was that volatility clusters are more predictable than direction.
*   **Execution:** Targeted `JPM` using the full S&P 500 advanced predictor matrix across Lags 1, 2, and 3.
*   **Result:** The Bayesian Ridge model still returned negative Out-of-Sample $R^2$ scores (-14.6% to -2.5%). 
*   **Conclusion:** Predicting day-to-day volatility magnitude using a linear combination of single-day technical indicators is just as difficult as predicting directional returns. Market efficiency remains dominant.

### 11. PyMC Bayesian Structural Time Series (BSTS) (`pymc_ebay_bsts_workflow.py`)
*   **Feature:** Upgraded the architecture to a state-space model, decomposing the return into a dynamic "Local Level" (Gaussian Random Walk) plus static covariates.
*   **Execution:** Targeted `EBAY` returns. Utilized the Rust-based `nutpie` sampler to bypass PyMC Windows compiler bottlenecks and drastically speed up the complex NUTS sampling.
*   **Result:** Highly negative $R^2$ (-189.7%) on Lag 1, indicating massive overfitting where the dynamic baseline memorized training noise. Lags 2 and 3 returned to near-zero/negative.
*   **Conclusion:** Explicitly modeling the time-varying nature of the series (drifting baseline) did not defeat market efficiency. The random walk baseline essentially proved that tomorrow's return is almost completely decoupled from today's state.

### 12. Automated Self-Healing & Pipeline Diagnostic QA
*   **Feature:** Transitioned the pipeline from brittle execution to a resilient, self-healing system with autonomous QA guardrails.
*   **Execution:** 
    *   Built `failover_downloader.py` with exponential backoff and direct Yahoo Chart API fallback to prevent intermittent `yfinance` failures from crashing the daily run. If all fallbacks fail, the asset is written to `quarantined_tickers.json`.
    *   Built `qa_models.py` which mathematically audits the Bayesian Scorecard outputs. If anomalies are detected (e.g. `P(UP) > 100%` or Expected Return `> 20%`), the model gracefully degrades to a V1 fallback or forces a `HOLD` instruction to the Virtual Broker.
    *   Built `qa_blacklist.py` to ensure the `blacklist_engine.py` is accurately parsing the ledger and isolating serial offenders.
    *   These QA scripts are natively bound to the master pipelines (`daily_pipeline.py` & `etf_daily_pipeline.py`) and dynamically inject HTML `⚠️ PIPELINE WARNING` banners into the morning email brief.

### 13. Intraday Execution Engine V2 (`intraday_tracker.py`)
*   **Feature:** Decoupled AI planning from market execution. The Night Pipeline now generates a `Pending_Orders.json` file instead of blindly executing trades at the overnight price. The Intraday Tracker wakes up during live market hours and strictly enforces a multi-layered momentum shield on ALL AI signals.
*   **Dynamic Persona Logic:** The engine scales risk boundaries based on the broker's Kelly multiplier mapping (BallsToTheWall: 1.0x, Neutral: 0.5x, Conservative: 0.25x).
*   **Execution Rules:**
    1.  **AI says BUY:** Enforces a Gap-Down Shield and a dynamic VWAP Premium Check. (Conservative requires `+1.0%` over VWAP; Neutral requires `+0.5%`; Balls requires `+0.25%`). If momentum fails, it triggers a `15:55 EST EOD Protocol` to permanently abort the trade.
    2.  **AI says HOLD:** Runs the *Take-Profit Surge Protocol* (selling if the stock surges `+5%`, `+10%`, or `+20%` depending on the broker) and the *Emergency Stop-Loss Plunge Protocol* (selling if the stock crashes `-5%`, `-10%`, or `-20%`).
    3.  **AI says SELL:** Runs the *Pending SELL Shield*. If the stock opens the day surging beyond the broker's VWAP Premium, it legally aborts the AI's sell instruction and holds the breakout.
*   **Result:** A fully symmetrical, omnipotent intraday execution engine that protects the portfolio from false AI signals and wild intraday volatility.

## Future Directions
If the project resumes, the focus should shift toward entirely different model architectures or data aggregations:
1.  **Non-Linear Deep Learning:** Explore LSTMs or Transformer models that can detect complex, non-linear sequence patterns that Bayesian Ridge regression fundamentally cannot.
2.  **Sector-Level Averages & Macro Data:** Instead of individual stocks, do entire sector movements provide a cleaner macroeconomic signal?
3.  **True Stochastic Volatility Models:** Implement a proper latent Stochastic Volatility (SV) or GARCH PyMC model rather than absolute return linear regression.
