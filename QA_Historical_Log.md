# QA Historical Log & Knowledge Base

This file serves as the permanent memory bank for the `QA_Engineer` subagent. 
It contains a historical record of all bugs discovered, root-cause analyses, deployed fixes, and regression test cases.

## Format Rules for QA Agent
Whenever you resolve a bug or create a test case, log it here using the following structure:

### [Date] - [Component Name] - [Bug Title / Test Case Title]
* **Symptom:** What went wrong / What is being tested?
* **Root Cause:** The underlying technical failure.
* **Resolution:** How the code was modified to fix it.
* **Test Case:** Steps or script used to verify the fix.

---
## Historical Logs

### 2026-06-03 - System - Initial QA Agent Activation
* **Symptom:** N/A (Initial Activation)
* **Root Cause:** N/A
* **Resolution:** QA Engineer subagent initialized and inspected repository structure. Execution of syntax check was skipped due to lack of immediate user execution approval (timed out), but repo structure looks intact. System is online.
* **Test Case:** N/A

### 2026-06-03 - Web App UI - Multiple Frontend Display & Sync Bugs
* **Symptom:** The historical equity curve line charts were completely missing from the dashboard. Switching Bayesian ledger tabs caused a `ReferenceError` crash. Additionally, switching tabs or personas while a specific ticker view was active caused the Bayesian data to become stale and display incorrectly.
* **Root Cause:** 1) Missing `<div id="line-stocks">` and `<div id="line-etfs">` in `index.html`. 2) Relying on deprecated global implicit `event` in `switchTableTab()` inline HTML calls. 3) The `loadHoldings` asynchronous function in `app.js` did not re-trigger `handleViewChange` after resetting the dropdown, leaving the page state desynchronized.
* **Resolution:** 1) Added the missing div containers in `index.html`. 2) Updated the `switchTableTab` signature in `app.js` and explicitly passed `this` in `index.html` inline onClick events. 3) Appended `await handleViewChange(prefix);` to the end of `loadHoldings` to force a view refresh.
* **Test Case:** Statically verified code alignment between `server.py` and `app.js`/`index.html`. Note: Dynamic HTTP verification was bypassed due to execution approval timeouts (user AFK).

### 2026-06-03 12:45:42 - QA Assistant - Dashboard API Bug Fix
* **Status:** SUCCESS - Fixed duplicated financial_data path in server.py.
* **Resolution:** Autopsy API route was silently dropping the Bayesian Dictionary due to an invalid relative path causing pd.read_excel to fail. Path corrected and backend verified.

### 2026-06-03 - Web App UI - Dashboard Styling & Browser Caching Bugs
* **Symptom:** The 3D CSS styling updates for the active tabs were not rendering for the user despite correct code logic. Additionally, the premium 3D sci-fi icons generated for the sub-tabs had solid black backgrounds that were visible on the cyan active tabs.
* **Root Cause:** 1) The user's browser was aggressively caching the static `style.css` file despite query string version bumping (`?v=8`) because FastAPI's `StaticFiles` returned 304 Not Modified. 2) The AI-generated sub-tab icons were PNGs rendered on pitch black rather than true transparent alpha channels.
* **Resolution:** 1) Completely broke the browser cache by physically renaming `style.css` to `style_3d.css` and updating the `index.html` link. 2) Wrote and executed a Python imaging script (`remove_bg.py`) to mathematically transform the pure black pixels (`#000000`) of the PNGs into a transparency alpha channel, perfectly preserving the glowing edge effects.
* **Test Case:** Visual verification by user. Icons now perfectly blend into colored tabs.

### 2026-06-04 11:26:14 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-04 13:00:58 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None

### 2026-06-04 11:26:14 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-04 13:00:58 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-04 13:54:03 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-05 08:48:54 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-06 - System / OS - Task Scheduler Stale Workspace Mismatch
* **Symptom:** Pipeline failed during execution (crashed on `GOOGL`), emails contained old artifacts (ugly logo), and changes made by the AI Assistant were seemingly completely ignored by the nightly run.
* **Root Cause:** The user migrated the primary workspace from OneDrive to a local path (`C:\Users\AviShemla\AntiGravity`). The AI Assistant correctly modified the local scripts. However, the Windows Task Scheduler was NEVER updated and continued to execute `run_pipeline.bat` from the stale `OneDrive` folder, which executed outdated scripts and stale portfolios.
* **Resolution:** The user manually updated the Windows Task Scheduler GUI to edit the `AntiGravity_Daily_Pipeline`, `AntiGravity_Git_AutoBackup`, and `AntiGravity_Weekend_Backtest` tasks to point directly to `C:\Users\AviShemla\AntiGravity`.
* **Test Case:** Verified paths using `schtasks /query /v /fo list` on the command line. Future QA cycles must explicitly query the Task Scheduler to verify absolute paths match the active workspace.

### 2026-06-06 10:12:44 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-06 - Mega-Macro Ghost Run - Pandas Timezone Bug
* **Symptom:** The `export_bayesian_scorecard_TNX.py` script crashed universally for all tickers, issuing `UNKNOWN` probabilities for the entire Active Portfolio.
* **Root Cause:** A timezone mismatch in `pd.concat` during the macro indicator merge (specifically `Yield_Curve_Spread`) caused `dropna()` to mercilessly delete the entire unified dataframe because the macroeconomic data was timezone-naive while the stock history was timezone-aware.
* **Resolution:** Injected `df_macro = df_macro.tz_localize(None)` prior to merging to explicitly strip the timezone data and guarantee a clean inner join.
* **Test Case:** Re-executed `export_bayesian_scorecard_TNX.py`. All active portfolio tickers successfully generated probabilities.

### 2026-06-06 - Intraday Execution Engine - Architecture Shift
* **Symptom:** Virtual Broker executed "paper trades" overnight, leaving the portfolio vulnerable to opening gaps and weak intraday momentum.
* **Root Cause:** Purely End-Of-Day (EOD) swing-trading logic explicitly committed to `Capital_Ledger_*.csv` in the middle of the night.
* **Resolution:** Intercepted Virtual Broker using a "Staging Mode" to output `Pending_Orders.json`. Deployed a continuous `intraday_tracker.py` loop to govern live execution based on VWAP and Yesterday's Close constraints, complete with a 15:55 EST EOD Fallback HOLD protocol.
* **Test Case:** Validated Staging Mode outputs correctly formatted JSON logic. Future QA cycles must verify `Pending_Orders.json` integrity and ensure it does not bloat.

### 2026-06-06 - Intraday Execution Engine - Ghost Cash Ledger Drift Bug
* **Symptom:** Total capital artificially inflated by exactly $20 per $1000 trade every time a momentum buy was approved.
* **Root Cause:** Night Pipeline blindly deducted cash based on `Yest_Close`. When Intraday Tracker triggered a momentum buy at a higher `Live_Price` (e.g. $102 instead of $100), the tracker updated the cost basis but failed to subtract the extra $2 from the cash balance, causing the ledger to mathematically drift away from reality.
* **Resolution:** Injected a Cash Refund block into `intraday_tracker.py`. The tracker now adds `units * yest_close` back to the cash pool to neutralize the night pipeline's blind deduction, and then cleanly subtracts `units * live_price` to mathematically lock the exact live execution cost into the ledger.
* **Test Case:** Full logic flow audit perfectly aligns.

### 2026-06-06 - Settlement Engine - Daily PnL Math Discrepancy
* **Symptom:** Night Pipeline settlement loop miscalculated actual daily profits for intraday-purchased assets.
* **Root Cause:** Both virtual brokers blindly used the Scorecard's `Actual Daily Return %` which is permanently pegged to `(Close - Yest_Close) / Yest_Close`. Because the sniper buys at the live intraday price (e.g., 9:30 AM open), using the Scorecard's static metric mathematically corrupted the PnL calculation.
* **Resolution:** Patched `virtual_broker.py` and `etf_virtual_broker.py` to pull the true `Close` price via yfinance during settlement and recalculate `actual_return_pct = (Close - Purchase_Price) / Purchase_Price`.
* **Test Case:** Logic flow math manually audited and verified. Syntax checks passed.

### 2026-06-06 - Intraday Execution Engine - Sequential Overwrite Amnesia Bug
* **Symptom:** Intraday Tracker would overwrite and completely erase its own live execution prices if it triggered multiple trades across different 10-minute intervals.
* **Root Cause:** At the start of every 10-minute loop, the tracker completely discarded its previous ledger state and rebuilt itself from the static overnight `Pending_Orders.json`. If `GOOG` was bought at 9:30 AM ($102) and `AAPL` was bought at 11:00 AM ($105), the 11:00 AM loop rebuilt `GOOG` from the overnight state ($100), erasing the 9:30 AM execution.
* **Resolution:** Deployed an `Executed_Intraday_Trades` memory bank payload into `Pending_Orders.json`. The tracker now permanently logs all live executions into the memory bank and iterates over the memory bank to rebuild the perfect live ledger state across every 10-minute tick.
* **Test Case:** Simulated data flow completely validates the memory bank retention architecture. Syntax compiled flawlessly.

### 2026-06-07 01:40:48 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-08 01:41:24 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-09 01:41:58 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-09 10:12:38 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-09 11:47:46 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-09 15:26:29 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-10 08:31:28 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-10 12:52:17 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-11 01:42:59 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-11 10:35:49 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: {'XLK': 'Blacklisted: 3 Strikes in 30d'}
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-12 01:42:06 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: {'XLK': 'Blacklisted: 3 Strikes in 30d'}
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-12 - PyTensor - Terminal Output I/O Bottleneck & Overflow Traces
* **Symptom:** Marathon Backtest experienced massive performance degradation, generating over 57,000 lines of console output and severely bottlenecking the CPU.
* **Root Cause:** PyMC PyTensor mathematical sampling threw thousands of non-fatal OverflowError: Python integer out of bounds for int8 tracebacks during NUTS MCMC iterations.
* **Resolution:** Optimized PyMC draws and 	une dynamically in engine_config.py from 1000/1000 down to 250/250 to accelerate sampling and slash output generation.
* **Test Case:** Implemented automated log volume/traceback assertions in the QA pipeline.

### 2026-06-12 - Marathon Core - UnboundLocalError & State Crash
* **Symptom:** un_backtests.py completely crashed right at the end of the simulation, destroying hours of compute.
* **Root Cause:** A local import json inside the un_simulation() exception block caused Python scoping rules to shadow the global json module, making json.load() throw an UnboundLocalError. 
* **Resolution:** Relocated import json to the global scope. Built an os.path.exists() hotfix mechanism to instantly recover orphaned 	mp_pred.json predictions without repeating hours of MCMC math.
* **Test Case:** Recovery loop dynamically bypassing subprocess.run() when JSON payloads already exist.

### 2026-06-12 - Intraday Execution Engine - Phantom Sell Authorizations
* **Symptom:** The Intraday ETF Sniper correctly identified and printed "SELL" logs, but the SQLite cash ledger completely ignored the trades.
* **Root Cause:** In intraday_tracker.py, the logical block identifying sells failed to append the dictionary payload into the pproved_sells list before initiating database settlement.
* **Resolution:** Injected direct append instructions into pproved_sells.append() and patched the VWAP / Live Price settlement logic to guarantee Cash is incremented.
* **Test Case:** Validated correct mutation of the pproved_sells payload array during evaluation cycles.

### 2026-06-12 - Deep Learning - ETF Data Leakage & Feature Scrambling
* **Symptom:** The Transformer Neural Network possessed 100% backtest accuracy but essentially random accuracy in live execution.
* **Root Cause:** etf_weekend_dl_trainer.py scaled the ENTIRE dataset using StandardScaler *before* train/test splitting, mathematically leaking future statistical variance. Furthermore, live inference columns were occasionally scrambled.
* **Resolution:** Enforced strictly chronological train/test isolation. Restricted scaler.fit() to Training Data only. Enforced absolute column alignment via scaler.feature_names_in_.
* **Test Case:** Assertions tracking chronological split independence and exact scaler feature alignment.

### 2026-06-13 01:43:05 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: {'XLK': 'Blacklisted: 3 Strikes in 30d'}
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-13 11:29:07 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-16 01:52:58 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-16 12:16:16 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-17 08:22:42 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-17 08:23:44 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-17 08:24:12 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** FAILURE - Pipeline aborted due to array mismatch or data corruption: 'SPY_Direction'
* **Resolution:** URGENT INVESTIGATION REQUIRED. Pipeline execution halted.

### 2026-06-17 08:24:46 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** FAILURE - Pipeline aborted due to array mismatch or data corruption: "None of [Index(['SPY_Lag4', 'GLD_Lag1', 'TNX_Lag3'], dtype='str')] are in the [columns]"
* **Resolution:** URGENT INVESTIGATION REQUIRED. Pipeline execution halted.

### 2026-06-17 08:25:10 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** FAILURE - Pipeline aborted due to array mismatch or data corruption: "None of [Index(['Target_RET_Lag1'], dtype='str')] are in the [columns]"
* **Resolution:** URGENT INVESTIGATION REQUIRED. Pipeline execution halted.

### 2026-06-17 08:25:43 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** FAILURE - Pipeline aborted due to array mismatch or data corruption: "None of [Index(['Target_DIR', 'Target_RET'], dtype='str')] are in the [columns]"
* **Resolution:** URGENT INVESTIGATION REQUIRED. Pipeline execution halted.

### 2026-06-17 08:26:44 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-17 08:47:57 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-17 21:12:24 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-17 21:15:53 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-18 01:00:08 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-18 01:37:53 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-18 01:42:45 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-18 01:43:03 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 09:06:07 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-19 09:32:44 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 09:41:21 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 21:15:31 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 21:24:14 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 21:34:09 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 21:44:25 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 21:54:08 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 22:03:47 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 22:13:25 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-19 22:22:34 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-20 01:00:05 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-21 01:00:07 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-22 01:00:06 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-22 13:12:56 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-23 01:23:39 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-23 10:32:12 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-23 12:11:30 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-23 13:01:12 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-24 01:00:26 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-24 07:56:34 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-25 01:00:36 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-25 01:23:17 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-25 01:38:58 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-25 09:14:14 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-26 01:00:08 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-26 01:19:40 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-26 01:20:56 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-27 01:00:32 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-28 01:00:40 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-06-28 09:40:14 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-06-30 02:26:28 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-02 02:20:55 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-04 02:21:25 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-07 02:22:07 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-07 07:22:59 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-08 05:34:41 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-09 02:20:50 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-10 09:38:24 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-11 02:19:54 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-13 11:10:07 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-14 02:21:49 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-15 02:20:50 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-15 14:03:38 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-17 01:00:37 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-18 14:43:51 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-18 14:56:10 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-18 15:01:51 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-19 01:00:37 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-19 10:09:12 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-19 10:09:47 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-19 10:15:16 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-19 10:21:50 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-19 11:22:07 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-19 11:32:44 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-19 14:17:25 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-20 02:12:59 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-20 08:51:53 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-20 14:18:37 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-21 02:11:28 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-21 08:35:34 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-21 12:18:04 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-22 02:09:21 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-23 10:52:49 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-24 02:09:54 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-24 10:49:42 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 10:29:29 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 11:42:28 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 11:43:02 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 11:43:35 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 11:46:53 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 12:48:50 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 13:35:34 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 13:36:37 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 14:36:49 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 14:40:35 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-25 18:17:07 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-30 09:00:52 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-07-31 18:26:56 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-31 18:42:59 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-31 18:45:42 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-31 18:56:07 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-07-31 19:30:19 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-08-06 02:05:57 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-08-07 02:05:53 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-08-08 02:05:22 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-08-11 16:43:57 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-08-12 02:04:25 - QA Assistant - Automated Blacklist Audit
* **Status:** SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: None
* **Resolution:** Blacklist pipeline logic is intact and generating correct output.

### 2026-10-30 14:50:34 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-10-30 17:25:41 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-10-30 17:27:38 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-10-30 17:28:30 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-10-30 17:29:27 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.


### 2026-10-30 17:45:00 - Full System (`v2.5-Deterministic-Lineage`) - $10,000.00 Inception Reconciliation, 7-Stage Traceability & 9/9 QA Green
* **Symptom:** 1) Pre-`2026-08-20` rows in `capital_ledgers` contained legacy duplicated carryover PnL (`ETF_BallsForBrains` inflated to `$15,001.71` / `+50%`) and multi-day cumulative return bugs (`ETF_Conservative` deflated to `$6,788.38` / `-32%`). 2) Post-`2026-08-20` equity curves flatlined due to Bayesian shrinkage making `payoff_ratio < 0.25` in Kelly sizing. 3) `prod_vs_shadow_master` had 31 legacy duplicate `'Prod'` rows (`$9,100`) colliding with `'PROD_Bayesian_SV'` (`$10,176.36`) on the Unified Arena chart. 4) `clean_ghosts.py` was missing `"prefect"` in `WHITELIST_KEYWORDS`.
* **Root Cause:** Legacy pre-Aug-20 virtual broker cumulative return calculations, unfloored single-day payoff ratio in Kelly formula, duplicate legacy model name keys in `prod_vs_shadow_master`, and incomplete process whitelist in `clean_ghosts.py`.
* **Resolution:**
  1. Patched `oracle_lineage_core.py` with bounded `effective_R = max(1.0, payoff_ratio)` when `expected_return > 0` and calibrated single-day Sharpe gates across all 8 personas.
  2. Rebuilt all `695+` ledger rows across all 8 personas from exact `$10,000.00` inception through `2026-10-30` using verified single-day market returns from Turso `yahoo_daily_prices`.
  3. Populated `feature_lineage_audit` (`1,017` rows) and `decision_lineage_audit` across `2026-08-21`..`2026-10-30` and enhanced `trace_decision.py` Stage 7 to prove `Prev_Dollars * Market_Return == Stored_Ticker_PnL`.
  4. Purged duplicate `'Prod'` rows from `prod_vs_shadow_master`, synced `2026-10-30` intraday monitoring rows across all 8 personas, whitelisted `"prefect"` in `clean_ghosts.py`, and added Check 3b (`>5%` Spike/Drop Anomaly), Check 4 (Anti-Flatline), and Check 5 (`$10,000.00` Inception) to `qa_financial_audit.py`.
* **Test Case:** Executed `py -u qa_manager.py` -> `FINAL QA STATUS: 100% GREEN (ALL PASSED)` across all 9 QA scripts; verified `trace_decision.py` and all 5 live dashboard tabs on `http://66.42.118.26:80`.

### 2026-10-30 17:53:04 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.


### 2026-11-06 09:10:00 - Intraday Execution & Catch-Up Engine (`ORA-INC-072` & `ORA-INC-073`) - ETF Carryover Exclusion, Historical `intraday_tracker` Self-Comparison Bug, and Batched Turso Lineage Writes
* **Symptom:**
  1. (`ORA-INC-072`): After Prefect's local state store (`/root/.prefect/prefect.db`) locked on `2026-10-31`, `intraday_tracker.py` generated `CARRYOVER (100% HOLD)` rows for the 4 Stock personas on `2026-11-03`..`2026-11-05` while skipping all 4 ETF personas (`ETF_Conservative`, `ETF_Neutral`, `ETF_Dynamic`, `ETF_BallsForBrains`), leaving a 3-day gap in ETF ledgers and copying yesterday's `Daily_PnL_JSON` into Stock carryover rows.
  2. (`ORA-INC-073`): During historical catch-up (`intraday_tracker.py --target-date YYYY-MM-DD`), because `virtual_broker.py` and `etf_virtual_broker.py` already persist the settled row for `target_date` into `capital_ledgers` (`if target_date_for_ledger < today_ny: save_ledger_row(...)`), `intraday_tracker.py` line 253 (`last_ledger_row = ledger.iloc[-1]`) loaded the newly written `target_date` row instead of the `T-1` prior day row, treating newly entered positions as already-held (`held_tickers`) instead of `new_buys`.
  3. Post-sampling Turso scorecard/lineage writes in `export_bayesian_scorecard_formatted.py` and `export_etf_scorecard.py` executed 248 individual synchronous HTTP round-trips per ticker (`~35s` per ticker).
* **Root Cause:**
  1. Line 203 of `intraday_tracker.py` filtered `WHERE persona NOT LIKE 'ETF_%'` and passed `last_row['Daily_PnL_JSON']` instead of `{}`.
  2. Line 253 of `intraday_tracker.py` used `ledger.iloc[-1]` without filtering `ledger['Date'] < state['Date']`.
  3. Row-by-row `execute_write` loops instead of `libsql_client` pipeline batching.
* **Resolution:**
  1. Backed up and removed the 12 placeholder `CARRYOVER (100% HOLD)` rows (`2026-11-03`..`2026-11-05`) from Turso `capital_ledgers` so all 8 personas cleanly replay chronologically from `2026-11-02` with zero skipped days.
  2. Patched `intraday_tracker.py` line 203 to include all 8 personas (`SELECT DISTINCT persona FROM capital_ledgers`) with `daily_pnl_json={}`, and patched line 253 to select `ledger[ledger['Date'].astype(str) < str(state['Date'])].iloc[-1]`.
  3. Added `build_decision_lineage_stmt()` and `execute_turso_batch()` (150 statements per HTTP batch) in `oracle_lineage_core.py` and wired both `export_bayesian_scorecard_formatted.py` and `export_etf_scorecard.py` to use batched Turso writes, plus 3-worker parallel ETF scorecard execution in `continuity_driver.py`.
* **Test Case:** Verified via `trace_decision.py --date 2026-11-03 --ticker ADM` and live Vultr/Turso readback (`verify_driver_alive.py`).


### 2026-11-06 11:35:00 - Bayesian Scorecard Engine (`ORA-INC-074`) - Multi-Threaded PyMC/PyTensor `futex_wait` Deadlock & Rust `nutpie` Dual-Head Sampler Acceleration
* **Symptom:** During `export_bayesian_scorecard_formatted.py --target-date 2026-11-03`, `PID 3866026` dropped to `6.1% CPU` with a `<defunct>` child (`PID 3866114`), and all 3 `ThreadPoolExecutor` worker threads (`SPID 3866103`, `3866104`, `3866105`) froze in `futex_wait` (`do_futex`) for `18+ minutes`.
* **Root Cause:** `export_bayesian_scorecard_formatted.py` spawned a `ThreadPoolExecutor(max_workers=3)` where 3 threads simultaneously called `run_with_timeout(run_sv_engine)` (spawning child processes via `multiprocessing.Process` inside threads) and then simultaneously constructed `pm.Model()` graphs inside the same Python process. PyMC/PyTensor's global model context and `multiprocessing.Queue` locks are not thread-safe on Linux. Additionally, the Dual-Head Bayesian model in both `export_bayesian_scorecard_formatted.py` and `export_etf_scorecard.py` defaulted to Python NUTS instead of `nuts_sampler="nutpie"`.
* **Resolution:**
  1. Replaced the `ThreadPoolExecutor` loop in `export_bayesian_scorecard_formatted.py` with a thread-safe sequential ticker loop and direct in-process `run_sv_engine()` execution.
  2. Replaced `run_with_timeout(run_sv_engine)` in `export_etf_scorecard.py` with direct `run_sv_engine()` execution (since `continuity_driver.py` runs ETF scorecards in separate OS processes).
  3. Added `nuts_sampler="nutpie"` (Rust NUTS with fallback) to the Dual-Head `pm.sample()` calls in both `export_bayesian_scorecard_formatted.py` and `export_etf_scorecard.py`.
* **Test Case:** Verified on Vultr (`PID 3866791`) at `11:36:27 UTC` (`98.7% CPU`, zero `<defunct>` processes, zero `futex_wait` deadlocks).

### 2026-11-06 15:12:18 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 15:17:31 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 15:44:42 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 18:00:42 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 19:00:50 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 20:00:46 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 21:00:53 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 21:02:27 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 22:00:48 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 22:02:18 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 23:00:39 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-06 23:02:08 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 00:01:13 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 00:03:23 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 01:00:55 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 01:01:06 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 01:02:31 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 01:02:39 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 02:00:51 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 02:02:21 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 03:00:42 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 03:02:12 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 04:00:47 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 04:02:14 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 05:00:47 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 05:02:16 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 06:00:45 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 06:02:20 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 07:00:40 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 07:02:07 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 08:01:19 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 08:03:20 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 08:25:03 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 08:28:42 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 09:00:49 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 09:02:23 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 10:00:45 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 10:02:23 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 11:00:47 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 11:02:19 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 11:04:00 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 12:00:42 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 13:00:41 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 14:00:45 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 15:00:45 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 16:00:45 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 17:00:41 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 18:00:49 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 19:00:40 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 20:00:45 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 21:00:37 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 22:00:45 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-07 23:00:49 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 00:00:54 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 01:00:53 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 01:01:05 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 02:00:40 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 03:00:50 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 04:00:38 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 05:00:46 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 05:24:38 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 06:00:43 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.

### 2026-11-08 07:00:44 - QA Assistant - Pre-Flight Data Alignment Check
* **Status:** SUCCESS - Data arrays perfectly aligned. NaN-bridge is active and healthy.
* **Resolution:** Safe to proceed with automated pipeline execution.


### 2026-11-09 08:10:00 - Pipeline Interlock & SSH Execution - [QA 10] Wall-Clock Date Overwrite & Paramiko Socket EOF Hang
* **Symptom:** 1) `qa_task_auditor.py` failed `[QA 10]` with `Interlock Violation: ETF Pipeline (2026-11-09) is ahead of Stock Pipeline (2026-11-06)`. 2) `execute_daily_migration.py` failed on Vultr with exit code 1. 3) Remote Python one-liners invoked via Paramiko SSH hung at EOF (`PipeTimeout`) when querying Turso (`libsql_client`).
* **Root Cause:** 1) `export_etf_broker_excel.py` line 324 called `database_manager.update_continuity("etf_pipeline", datetime.datetime.now().strftime("%Y-%m-%d"))`, overwriting the true market session date (`2026-11-06`) with the wall-clock date (`2026-11-09`). 2) `execute_daily_migration.py` hardcoded a Windows local `PYTHON_EXE` path (`C:\Users\AviShemla\...`) instead of `sys.executable`. 3) Remote `python -c` commands that import `database_manager` (`libsql_client` / `aiohttp` connection pool) without calling `os._exit(0)` keep the remote SSH stdout pipe open indefinitely at EOF.
* **Resolution:** 1) Patched `export_etf_broker_excel.py` to sync `etf_pipeline` continuity to the `master_pipeline` completed session date in Turso instead of `datetime.now()`. 2) Patched `execute_daily_migration.py` to use `sys.executable` and `qa_manager.py`. 3) Enforced `sys.stdout.flush(); os._exit(0)` on all remote SSH Python invocations (`vultr_status_and_heal.py`).
* **Test Case:** Executed `vultr_status_and_heal.py` (`task-26708`), verified `process_continuity` shows `master_pipeline = 2026-11-06` and `etf_pipeline = 2026-11-06`, and verified `qa_task_auditor.py` passed `11/11 Checks Green` and `qa_manager.py` passed `9/9 Suites Green`.
