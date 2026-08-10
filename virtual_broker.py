import pandas as pd
import numpy as np
import os
import json
import sys
from blacklist_engine import get_blacklisted_tickers
import database_manager

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
EXCEL_PATH = os.path.join(BASE_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx')

PERSONAS = {
    "Conservative": {
        "threshold": 0.65,
        "kelly_multiplier": 0.25,
        "max_alloc": 0.10,
        "flat_fallback": 0.0,
        "ignore_kelly": False
    },
    "Neutral": {
        "threshold": 0.60,
        "kelly_multiplier": 0.50,
        "max_alloc": 0.10,
        "flat_fallback": 0.10,
        "ignore_kelly": False
    },
    "BallsForBrains": {
        "threshold": 0.55,
        "kelly_multiplier": 0.9,
        "max_alloc": 0.15,
        "flat_fallback": 0.15,
        "ignore_kelly": False
    }
}

def calculate_kelly_fraction(prob, expected_return, expected_volatility):
    if expected_return <= 0 or expected_volatility <= 0:
        return 0.0
    R = expected_return / expected_volatility
    W = prob
    kelly_pct = W - ((1 - W) / R)
    return max(0.0, kelly_pct)

def run_virtual_broker():
    print("=== MULTI-PERSONA VIRTUAL BROKER EXECUTION ===\n")
    
    # --- GLOBAL VIX FETCH FOR DYNAMIC STOP LOSSES ---
    global_vix_hist = pd.DataFrame()
    try:
        import yfinance as yf
        global_vix_hist = yf.Ticker('^VIX').history(period='30d')
    except:
        pass
    # SOURCE OF TRUTH: Turso DB etf_scorecards_master
    is_etf_mode = len(sys.argv) > 1 and sys.argv[1] == "ETF"
    persona_prefix = "ETF_" if is_etf_mode else ""

    # Derive target date
    if len(sys.argv) > 2 and "Capital" not in sys.argv[2]:
        target_date_global = sys.argv[2]
    else:
        target_date_global = None  # will be resolved per-persona from DB

    # Load full scorecard from DB for today (or latest available date)
    try:
        ref_persona = f"{persona_prefix}BallsForBrains"
        if target_date_global:
            scorecard_date = target_date_global
        else:
            date_res = database_manager.execute_query(
                "SELECT MAX(date) as d FROM etf_scorecards_master WHERE persona=?",
                [ref_persona]
            )
            scorecard_date = date_res.iloc[0][0] if not date_res.empty else pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d')

        df_scorecard_all = database_manager.execute_query(
            "SELECT ticker, persona, date, prob, expected_return, expected_risk, kelly_allocation, "
            "recommendation, broker_override_note, retraining_status, actual_return "
            "FROM etf_scorecards_master WHERE date <= ? ORDER BY date DESC",
            [scorecard_date]
        )
        if df_scorecard_all.empty:
            print(f"[ABORT] No scorecard data in DB for date <= {scorecard_date}. Cannot run broker.")
            return

        # Get ticker universe from latest date
        ticker_universe = df_scorecard_all[df_scorecard_all['date'] == df_scorecard_all['date'].max()]['ticker'].unique().tolist()
        print(f"Ticker universe from DB ({scorecard_date}): {ticker_universe}")
    except Exception as e:
        print(f"[ABORT] Failed to load scorecard from Turso DB: {e}")
        return

    def get_scorecard_row(ticker, target_date, persona):
        """Get the latest scorecard row for a ticker/persona up to target_date from pre-loaded DF."""
        sub = df_scorecard_all[
            (df_scorecard_all['ticker'] == ticker) &
            (df_scorecard_all['persona'] == persona) &
            (df_scorecard_all['date'] <= target_date)
        ]
        if sub.empty:
            return None
        return sub.sort_values('date').iloc[-1]

    def get_settlement_row(ticker, settlement_date, persona):
        """Get scorecard row for a specific settlement date (T-1)."""
        sub = df_scorecard_all[
            (df_scorecard_all['ticker'] == ticker) &
            (df_scorecard_all['persona'] == persona) &
            (df_scorecard_all['date'] == settlement_date)
        ]
        if sub.empty:
            return None
        return sub.iloc[-1]

    final_equities = {}

    # --- DYNAMIC ALLOCATOR (SHARPE RATIO) — reads from Turso DB ---
    dynamic_winner = "Neutral"
    try:
        sharpe_scores = {}
        for p in ["Conservative", "Neutral", "BallsForBrains"]:
            p_name = f"{persona_prefix}{p}"
            df_p = database_manager.get_ledger(p_name)
            if not df_p.empty and len(df_p) >= 10:
                df_p['Return'] = df_p['Total_Equity'].pct_change()
                recent = df_p['Return'].tail(30).dropna()
                if recent.std() > 0:
                    sharpe = (recent.mean() / recent.std()) * np.sqrt(252)
                    sharpe_scores[p] = sharpe
        if sharpe_scores:
            dynamic_winner = max(sharpe_scores, key=sharpe_scores.get)
            print(f"--- DYNAMIC ALLOCATOR ---")
            print(f"30-Day Sharpe Leaderboard: { {k: round(v,2) for k,v in sharpe_scores.items()} }")
            print(f"Dynamic Capital Reallocated to: {dynamic_winner}\n")
    except Exception as e:
        print(f"Error calculating Sharpe: {e}")
        
    runtime_personas = PERSONAS.copy()
    runtime_personas["Dynamic"] = PERSONAS[dynamic_winner].copy()
    
    for persona_name, config in runtime_personas.items():
        full_persona = f"{persona_prefix}{persona_name}"
        print(f"--- Persona: {full_persona.upper()} ---")
        print(f"Rules: Buy if P > {config['threshold']:.2f} | {config['kelly_multiplier']}x Kelly | Max {config['max_alloc']*100}% per stock")

        # 1. Initialize or load ledger from Turso DB
        ledger = database_manager.get_ledger(full_persona)
        if ledger.empty:
            ledger = pd.DataFrame([{
                'Date': '2026-04-22',
                'Cash': 10000.0,
                'Total_Equity': 10000.0,
                'Holdings_JSON': '{}',
                'Daily_PnL_JSON': '{}'
            }])

        target_date_for_ledger = scorecard_date

        if not ledger.empty and target_date_for_ledger == str(ledger['Date'].iloc[-1]):
            print(f"  [IDEMPOTENT OVERWRITE] Re-executing for date {target_date_for_ledger}.")
            # Integrity: ensure we have at least some tickers in DB for this date
            tickers_today = df_scorecard_all[
                (df_scorecard_all['date'] == scorecard_date) &
                (df_scorecard_all['persona'] == full_persona)
            ]['ticker'].tolist()
            if len(tickers_today) == 0:
                print(f"  [INTEGRITY FAILURE] No scorecard rows in DB for {scorecard_date}/{full_persona}. Aborting overwrite.")
                final_equities[full_persona] = float(ledger['Total_Equity'].iloc[-1])
                continue
            else:
                print(f"  [INTEGRITY PASSED] {len(tickers_today)} tickers in DB for today. Proceeding.")
            
            last_state = ledger.iloc[-2] if len(ledger) >= 2 else pd.Series({
                'Date': '2026-04-22', 'Cash': 10000.0, 'Total_Equity': 10000.0, 
                'Holdings_JSON': '{}', 'Daily_PnL_JSON': '{}'
            })
        else:
            last_state = ledger.iloc[-1]
        
        current_cash = float(last_state['Cash'])
        total_equity = float(last_state['Total_Equity'])
        holdings = json.loads(last_state['Holdings_JSON'])
        
        # 2. Settle yesterday's trades based on actual returns
        settled_equity = current_cash
        daily_pnl = {}
        
        skip_sheets = set()
        for ticker in ticker_universe:
            # Get last 2 rows from DB up to target date for settlement
            sub = df_scorecard_all[
                (df_scorecard_all['ticker'] == ticker) &
                (df_scorecard_all['persona'] == full_persona) &
                (df_scorecard_all['date'] <= target_date_for_ledger)
            ].sort_values('date')
            sheet = ticker  # alias for compatibility with rest of code
            if len(sub) < 2:
                skip_sheets.add(ticker)
                continue
            settlement_row = sub.iloc[-2]
            pending_row = sub.iloc[-1]
            
            if ticker in holdings:
                item = holdings[ticker]
                if isinstance(item, dict):
                    allocated_dollars = item.get("dollars", 0.0)
                else:
                    allocated_dollars = float(item)

                actual_return_pct = settlement_row.get('actual_return', None)
                
                if pd.notna(actual_return_pct):
                    # --- INTRA-DAY STOP-LOSS ONLY (scorecard return is the source of truth for PnL) ---
                    # CRITICAL: We NEVER override actual_return_pct with a yfinance total-since-purchase
                    # return, as this causes multi-day PnL accumulation (phantom gains) when yfinance
                    # intermittently fails. The scorecard's actual daily return % is always correct.
                    purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                    if purchase_price > 0:
                        try:
                            settle_date_str = settlement_row[sheet_date_col].strftime('%Y-%m-%d')
                            hist = yf.Ticker(sheet).history(start=settle_date_str, end=target_date_for_ledger)
                            if not hist.empty:
                                low_price = hist['Low'].iloc[0]
                                
                                # STOP-LOSS CHECK ONLY: Only override return if a hard stop-loss was hit
                                dynamic_stop_loss = -0.05
                                vix_high = 0.0
                                if not global_vix_hist.empty:
                                    try:
                                        if settle_date_str in global_vix_hist.index.strftime('%Y-%m-%d'):
                                            vix_high = global_vix_hist[global_vix_hist.index.strftime('%Y-%m-%d') == settle_date_str]['High'].iloc[0]
                                        else:
                                            vix_high = global_vix_hist['High'].iloc[-1]
                                            
                                        if persona_name == "Conservative":
                                            dynamic_stop_loss = -0.010 if vix_high > 35.0 else (-0.025 if vix_high > 25.0 else -0.040)
                                        elif persona_name == "Neutral":
                                            dynamic_stop_loss = -0.020 if vix_high > 35.0 else (-0.035 if vix_high > 25.0 else -0.050)
                                        else: # BallsForBrains / Dynamic
                                            dynamic_stop_loss = -0.030 if vix_high > 35.0 else (-0.045 if vix_high > 25.0 else -0.060)
                                    except: pass
                                
                                intraday_drop = (low_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0
                                if intraday_drop <= dynamic_stop_loss:
                                    panic_str = f"(VIX {vix_high:.1f})" if vix_high > 0 else ""
                                    print(f"  [STOP-LOSS TRIGGERED] {sheet} dropped {intraday_drop*100:.1f}% intraday! Intercepting loss at {dynamic_stop_loss*100:.1f}% {panic_str}")
                                    actual_return_pct = dynamic_stop_loss  # Only override for stop-loss
                        except:
                            pass
                    # -------------------------------------------------------------------------
                    
                    pnl = allocated_dollars * actual_return_pct
                    daily_pnl[sheet] = pnl
                    settled_equity += (allocated_dollars + pnl)
                else:
                    daily_pnl[sheet] = 0.0
                    settled_equity += allocated_dollars
                    
        # --- ZOMBIE FAILSAFE LOGIC ---
        for held_ticker, item in holdings.items():
            if held_ticker not in ticker_universe or held_ticker in skip_sheets:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                
                try:
                    from failover_downloader import download_ticker_with_failover
                    hist = download_ticker_with_failover(held_ticker, start=(pd.to_datetime(target_date_for_ledger) - pd.Timedelta(days=5)).strftime('%Y-%m-%d'))
                    hist = hist[hist.index <= pd.to_datetime(target_date_for_ledger)]
                    if not hist.empty and purchase_price > 0:
                        latest_price = hist['Close'].dropna().iloc[-1]
                        actual_return_pct = (latest_price - purchase_price) / purchase_price
                        pnl = allocated_dollars * actual_return_pct
                        daily_pnl[held_ticker] = pnl
                        settled_equity += (allocated_dollars + pnl)
                        print(f"  [ZOMBIE RECOVERED] {held_ticker} active (Network glitch). Settled via emergency fetch. PnL: ${pnl:.2f}")
                    else:
                        print(f"  [ZOMBIE FAILSAFE TRIGGERED] {held_ticker} returned empty data (Likely delisted, M&A, or Ticker Change)!")
                        print(f"  Force liquidating {held_ticker} at purchase price. Returning ${allocated_dollars:.2f} to Cash.")
                        daily_pnl[held_ticker] = 0.0
                        settled_equity += allocated_dollars
                except Exception as e:
                    print(f"  [ZOMBIE FAILSAFE ERROR] Could not verify {held_ticker}: {e}. Returning capital to Cash.")
                    daily_pnl[held_ticker] = 0.0
                    settled_equity += allocated_dollars
        # -----------------------------
                    
        # --- MULTI-TIERED PERSONA VIX LOGIC ---
        vix_multiplier = 1.0
        vix_triggered = False
        latest_vix = 15.0
        
        vix_path = os.path.join(BASE_DIR, "financial_data", "vix_score.json")
        try:
            if os.path.exists(vix_path):
                with open(vix_path, 'r') as f:
                    latest_vix = float(json.load(f).get("vix_value", 15.0))
            else:
                import yfinance as yf
                vix_hist = yf.Ticker('^VIX').history(period='5d')
                if not vix_hist.empty:
                    latest_vix = float(vix_hist['Close'].dropna().iloc[-1])
                    
            if "Conservative" in persona_name:
                if latest_vix > 25.0:
                    vix_multiplier = 0.0
                    vix_triggered = True
                    print(f"  [VIX PANIC - CONSERVATIVE] Extreme Fear (^VIX = {latest_vix:.2f} > 25.0). Retreating to 100% Cash.")
                elif latest_vix > 20.0:
                    vix_multiplier = 0.3
                    print(f"  [VIX ELEVATED] Conservative Risk Off (^VIX = {latest_vix:.2f}). Kelly -> 0.3x")
                    
            elif "BallsToTheWall" in persona_name or "Balls" in persona_name:
                if latest_vix > 45.0:
                    vix_multiplier = 0.0
                    vix_triggered = True
                    print(f"  [VIX MELTDOWN - BALLSFORBRAINS] Global Crisis (^VIX = {latest_vix:.2f} > 45.0). Retreating to 100% Cash.")
                elif latest_vix > 35.0:
                    vix_multiplier = 0.8
                    print(f"  [VIX ELEVATED] BallsForBrains slightly reducing exposure (^VIX = {latest_vix:.2f}). Kelly -> 0.8x")
                    
            else: # Neutral
                if latest_vix > 30.0:
                    vix_multiplier = 0.0
                    vix_triggered = True
                    print(f"  [VIX PANIC - NEUTRAL] Extreme Fear (^VIX = {latest_vix:.2f} > 30.0). Retreating to 100% Cash.")
                elif latest_vix > 20.0:
                    vix_multiplier = 0.8
                    print(f"  [VIX ELEVATED] Neutral Risk Off (^VIX = {latest_vix:.2f}). Kelly -> 0.8x")
                    
        except Exception as e:
            print(f"  [VIX ERROR] Failed to fetch VIX state: {e}")
        # ---------------------------
        
        # 3. Calculate new allocations for tomorrow
        new_holdings = {}
        new_cash = settled_equity
        available_capital = settled_equity
        
        blacklisted = get_blacklisted_tickers(persona=persona_name)
        if blacklisted:
            print(f"  [BLACKLIST_ENGINE] Active Blacklist for {persona_name}: {', '.join(blacklisted)}")
            
        for held_ticker, item in holdings.items():
            if held_ticker in blacklisted and held_ticker not in new_holdings:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                if allocated_dollars > 0:
                    current_value = allocated_dollars + daily_pnl.get(held_ticker, 0.0)
                    print(f"  [QUARANTINE] Retaining existing position in {held_ticker} without allocating new capital.")
                    new_holdings[held_ticker] = {"dollars": current_value, "price": purchase_price}
                    new_cash -= current_value
                    available_capital -= current_value
                    
        # --- HOLDING PROTECTION: FREEZE QUARANTINED OR V1-DEGRADED POSITIONS — reads from Turso DB ---
        for held_ticker, item in holdings.items():
            if held_ticker in ticker_universe and held_ticker not in new_holdings:
                try:
                    sc_row = get_scorecard_row(held_ticker, target_date_for_ledger, full_persona)
                    if sc_row is not None:
                        override_note = str(sc_row.get('broker_override_note', '') or '')
                        status = str(sc_row.get('retraining_status', '') or '')

                        is_frozen = ("QUARANTINED" in status) or ("QUARANTINED" in override_note) or ("Held Position Frozen" in override_note)

                        if is_frozen:
                            allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                            purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                            held_units = int(item.get("units", 0)) if isinstance(item, dict) else 0
                            if allocated_dollars > 0:
                                current_value = allocated_dollars + daily_pnl.get(held_ticker, 0.0)
                                print(f"  [HOLDING PROTECTION] Freezing existing position in {held_ticker} due to data/model fallback.")
                                new_holdings[held_ticker] = {"dollars": current_value, "price": purchase_price, "units": held_units}
                                new_cash -= current_value
                                available_capital -= current_value
                except Exception as e:
                    print(f"  Error checking holding protection for {held_ticker}: {e}")
                    
        import yfinance as yf
        import sector_gravity
        gravity_map = sector_gravity.build_gravity_map()
        stock_to_etf = sector_gravity.load_stock_to_etf_map()
        
        for ticker in ticker_universe:
            sheet = ticker  # alias
            if ticker in new_holdings:
                continue
            if ticker in blacklisted:
                print(f"  [BLACKLIST] Broker refused to allocate capital for {ticker} due to 3 autopsy strikes.")
                continue

            # Get latest scorecard row from Turso DB
            sc_row = get_scorecard_row(ticker, target_date_for_ledger, full_persona)
            if sc_row is None:
                continue

            prob = float(sc_row.get('prob', 0) or 0)
            exp_ret = float(sc_row.get('expected_return', 0) or 0)
            exp_vol = float(sc_row.get('expected_risk', 0) or 0)
            status = str(sc_row.get('retraining_status', 'Stable') or 'Stable')

            if "SUSPENDED" in status: continue
                
            if prob > config['threshold']:
                if vix_multiplier == 0.0:
                    print(f"  [BLOCKED BY VIX] Skipped {sheet} (P={prob*100:.1f}%) due to extreme market volatility.")
                    continue
                    
                if available_capital <= 0:
                    print(f"  [SAFETY STOP] Cannot buy {sheet} (P={prob*100:.1f}%) - Account funds completely depleted ($0.00)!")
                    continue
                    
                raw_kelly = calculate_kelly_fraction(prob, exp_ret, exp_vol)
                
                if config.get('ignore_kelly', False):
                    applied_kelly = config.get('flat_fallback', 0.0) * vix_multiplier
                else:
                    applied_kelly = raw_kelly * config['kelly_multiplier'] * vix_multiplier
                    if applied_kelly == 0 and config.get('flat_fallback', 0.0) > 0:
                        applied_kelly = config['flat_fallback'] * vix_multiplier
                        
                final_allocation_pct = min(applied_kelly, config['max_alloc'])
                
                if final_allocation_pct > 0:
                    raw_alloc_dollars = available_capital * final_allocation_pct
                    if raw_alloc_dollars > new_cash:
                        raw_alloc_dollars = new_cash
                        
                    try:
                        # Fetch latest close price using Tiingo Fallback engine
                        from failover_downloader import download_ticker_with_failover
                        ticker_data = download_ticker_with_failover(sheet, start=(pd.to_datetime(target_date_for_ledger) - pd.Timedelta(days=5)).strftime('%Y-%m-%d'))
                        ticker_data = ticker_data[ticker_data.index <= pd.to_datetime(target_date_for_ledger)]
                        if not ticker_data.empty:
                            latest_price = ticker_data['Close'].dropna().iloc[-1]
                            units = int(raw_alloc_dollars // latest_price)
                            alloc_dollars = units * latest_price
                            
                            # STRICT FAILSAFE: Enforce absolute maximum cap
                            max_allowed_dollars = settled_equity * config['max_alloc']
                            if alloc_dollars > max_allowed_dollars:
                                alloc_dollars = max_allowed_dollars
                                units = int(alloc_dollars // latest_price)
                                alloc_dollars = units * latest_price
                        else:
                            # Fallback if yfinance fails
                            units = 0
                            latest_price = 0
                            alloc_dollars = 0.0
                    except Exception as e:
                        import logging
                        logging.error(f"FATAL API DROP for {sheet} on {target_date_for_ledger}. Error: {e}. Retrying aggressively...")
                        import time
                        try:
                            time.sleep(2)
                            ticker_data = download_ticker_with_failover(sheet, start=(pd.to_datetime(target_date_for_ledger) - pd.Timedelta(days=10)).strftime('%Y-%m-%d'))
                            ticker_data = ticker_data[ticker_data.index <= pd.to_datetime(target_date_for_ledger)]
                            if not ticker_data.empty:
                                latest_price = ticker_data['Close'].dropna().iloc[-1]
                                units = int(raw_alloc_dollars // latest_price)
                                alloc_dollars = units * latest_price
                                
                                # STRICT FAILSAFE: Enforce absolute maximum cap
                                max_allowed_dollars = settled_equity * config['max_alloc']
                                if alloc_dollars > max_allowed_dollars:
                                    alloc_dollars = max_allowed_dollars
                                    units = int(alloc_dollars // latest_price)
                                    alloc_dollars = units * latest_price
                            else:
                                raise ValueError("Retry yielded empty dataframe")
                        except Exception as e2:
                            logging.error(f"Aggressive retry completely failed for {sheet}. Failsafe dropping to cash. {e2}")
                            units = 0
                            latest_price = 0
                            alloc_dollars = 0.0
                        
                    if alloc_dollars > 0:
                        # Save complex struct to JSON for the exporter to read
                        new_holdings[sheet] = {
                            "dollars": alloc_dollars,
                            "units": units,
                            "price": latest_price
                        }
                        new_cash -= alloc_dollars
                        if units > 0:
                            print(f"  [BUY] {sheet} | {units} units @ ${latest_price:.2f} = ${alloc_dollars:.2f} (P={prob*100:.1f}%)")
                        else:
                            print(f"  [BUY] {sheet} | Alloc: ${alloc_dollars:.2f} (P={prob*100:.1f}%)")
        
        if not new_holdings:
            print("  [HOLD] Sitting safely in Cash.")
            
        print(f"  End of Day Equity: ${settled_equity:.2f} (Cash: ${new_cash:.2f})\n")

        # 4. Save intended state to Pending Orders — to Turso DB
        intended_state = {
            "Persona": full_persona,
            "Date": target_date_for_ledger,
            "Target_Cash": round(new_cash, 2),
            "Target_Total_Equity": round(settled_equity, 2),
            "Target_Holdings": {k: {"dollars": round(v["dollars"], 2), "units": v["units"], "price": v["price"]} for k, v in new_holdings.items()},
            "Daily_PnL_JSON": {k: round(v, 2) for k, v in daily_pnl.items()},
            "Executed_Intraday_Trades": {}
        }

        database_manager.save_pending_order(
            persona=full_persona,
            date=intended_state["Date"],
            target_cash=intended_state["Target_Cash"],
            target_equity=intended_state["Target_Total_Equity"],
            target_holdings=intended_state["Target_Holdings"],
            daily_pnl=intended_state["Daily_PnL_JSON"],
            executed_trades=intended_state["Executed_Intraday_Trades"]
        )

        print(f"  [STAGING MODE] Delegated execution for {full_persona} to Intraday Tracker. Saved to Pending_Orders.")

        final_equities[full_persona] = settled_equity

    # LEADERBOARD
    print("=== LIVE LEADERBOARD ===")
    sorted_equities = sorted(final_equities.items(), key=lambda x: x[1], reverse=True)
    rank = 1
    for name, eq in sorted_equities:
        profit = eq - 10000.0
        print(f"#{rank} {name.ljust(15)} : ${eq:,.2f}  (Profit: ${profit:+,.2f})")
        rank += 1
        
if __name__ == '__main__':
    run_virtual_broker()
    import sys; sys.stdout.flush(); os._exit(0)
