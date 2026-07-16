import pandas as pd
import numpy as np
import os
import json
import database_manager

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
try:
    with open(os.path.join(BASE_DIR, 'Dynamic_Target_ETFs.json'), 'r') as f:
        TARGET_ETFS = json.load(f)
except:
    TARGET_ETFS = ["XLK"]

PERSONAS = {
    "Conservative": {"threshold": 0.57, "kelly_multiplier": 0.25, "max_alloc": 0.10},
    "Neutral": {"threshold": 0.54, "kelly_multiplier": 0.50, "max_alloc": 0.10},
    "BallsForBrains": {"threshold": 0.51, "kelly_multiplier": 1.0, "max_alloc": 0.10}
}

def calculate_kelly_fraction(prob, expected_return, expected_volatility):
    # ETFs are highly symmetrical on daily timescales.
    # If the Bayesian engine heavily shrinks the expected return, we default to an even-money bet (R=1.0)
    # This prevents the Kelly formula from freezing capital when probability is solid but magnitude is shrunken.
    R = 1.0
    if expected_return > 0 and expected_volatility > 0:
        calculated_R = expected_return / expected_volatility
        if calculated_R > 0.1: # Only use if the ratio is statistically significant
            R = calculated_R
            
    W = prob
    kelly_pct = W - ((1 - W) / R)
    return max(0.0, kelly_pct)

def run_etf_virtual_broker():
    print("=== MULTI-PERSONA MULTI-ETF VIRTUAL BROKER EXECUTION ===\n")
    
    # --- GLOBAL VIX FETCH FOR DYNAMIC STOP LOSSES ---
    global_vix_hist = pd.DataFrame()
    try:
        import yfinance as yf
        global_vix_hist = yf.Ticker('^VIX').history(period='30d')
    except:
        pass
    
    scorecards = {}
    for etf in TARGET_ETFS:
        path = os.path.join(BASE_DIR, f'{etf}_Bayesian_Scorecard.xlsx')
        if os.path.exists(path):
            try:
                xls = pd.ExcelFile(path)
                df = pd.read_excel(xls, sheet_name=etf, skiprows=2)
                if len(df) >= 2:
                    scorecards[etf] = df
            except:
                pass
                
    if not scorecards:
        print("No valid ETF scorecards found!")
        return

    first_df = list(scorecards.values())[0]
    if first_df.empty:
        print("  [SAFETY STOP] ETF Scorecard is completely empty. Rolling over ledger with 0 PnL.")
        last_scorecard_date = pd.Timestamp.now(tz='America/New_York')
    else:
        last_scorecard_date = pd.to_datetime(first_df.iloc[-1]['Date'])
    
    try:
        import sys
        if len(sys.argv) > 2 and "Capital" not in sys.argv[2]:
            target_date_for_ledger = sys.argv[2]
            
            date_col = 'date' if 'date' in first_df.columns else 'Date'
            if not first_df.empty and not (pd.to_datetime(first_df[date_col]) == pd.to_datetime(target_date_for_ledger)).any():
                print(f"[WARNING] Target date {target_date_for_ledger} not found in first scorecard ({list(scorecards.keys())[0]}). Skipping date validation lock to allow fresh scorecards to process.")
        else:
            import pandas_market_calendars as mcal
            nyse = mcal.get_calendar('NYSE')
            now = pd.Timestamp.now(tz='America/New_York')
            past = now - pd.Timedelta(days=7)
            future = now + pd.Timedelta(days=7)
            schedule = nyse.schedule(start_date=past.strftime('%Y-%m-%d'), end_date=future.strftime('%Y-%m-%d'))
            next_sessions = schedule[schedule.index > last_scorecard_date]
            if not next_sessions.empty:
                target_date_for_ledger = next_sessions.iloc[0].name.strftime('%Y-%m-%d')
            else:
                target_date_for_ledger = (last_scorecard_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    except Exception as e:
        print(f"Calendar error: {e}, falling back to +1 day")
        target_date_for_ledger = (last_scorecard_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

    # --- CRITICAL FIX: Filter Scorecards by Target Date ---
    filtered_scorecards = {}
    for etf, df in scorecards.items():
        date_col = 'date' if 'date' in df.columns else 'Date'
        filtered_df = df[pd.to_datetime(df[date_col]) <= pd.to_datetime(target_date_for_ledger)]
        if len(filtered_df) >= 2:
            filtered_scorecards[etf] = filtered_df
    scorecards = filtered_scorecards
    # ------------------------------------------------------

    final_equities = {}
    
    # --- DYNAMIC ALLOCATOR (SHARPE RATIO) ---
    dynamic_winner = "Neutral"
    try:
        sharpe_scores = {}
        for p in ["Conservative", "Neutral", "BallsForBrains"]:
            p_ledger = os.path.join(BASE_DIR, f'ETF_Capital_Ledger_{p}.csv')
            if os.path.exists(p_ledger):
                df_p = pd.read_csv(p_ledger)
                if len(df_p) >= 10:
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
        print(f"--- Persona: {persona_name.upper()} ---")
        
        ledger = database_manager.get_ledger(f"ETF_{persona_name}")
        if ledger.empty:
            ledger = pd.DataFrame([{
                'Date': '2026-04-22',
                'Cash': 10000.0,
                'Total_Equity': 10000.0,
                'Holdings_JSON': '{}',
                'Daily_PnL_JSON': '{}'
            }])
        
        if not ledger.empty and str(target_date_for_ledger) == str(ledger['Date'].iloc[-1]):
            print(f"  [IDEMPOTENT OVERWRITE] Re-executing for date {target_date_for_ledger}. Checking Scorecard Integrity...")
            missing_count = len(TARGET_ETFS) - len(scorecards)
            if missing_count > len(TARGET_ETFS) * 0.35:
                print(f"  [INTEGRITY FAILURE] Scorecards are highly corrupted ({missing_count} missing/empty ETFs). Aborting overwrite to protect ledger.")
                final_equities[persona_name] = float(ledger['Total_Equity'].iloc[-1])
                continue
            else:
                print("  [INTEGRITY PASSED] Proceeding with ledger overwrite.")
            
            last_state = ledger.iloc[-2] if len(ledger) >= 2 else pd.Series({
                'Date': '2026-04-22', 'Cash': 10000.0, 'Total_Equity': 10000.0, 
                'Holdings_JSON': '{}', 'Daily_PnL_JSON': '{}'
            })
        else:
            last_state = ledger.iloc[-1]
        current_cash = float(last_state['Cash'])
        total_equity = float(last_state['Total_Equity'])
        holdings = json.loads(last_state['Holdings_JSON'])
        
        settled_equity = current_cash
        daily_pnl = {}
        
        # 1.5 Settle Orphaned Trades (ETFs dropped from the Dynamic Top 10)
        for held_etf, item in list(holdings.items()):
            if held_etf not in scorecards:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                print(f"  [ORPHAN LIQUIDATION] {held_etf} dropped from Top 10 rankings! Liquidating position to free capital...")
                
                actual_return_pct = 0.0
                if purchase_price > 0:
                    try:
                        from failover_downloader import download_ticker_with_failover
                        hist = download_ticker_with_failover(held_etf, period='5d')
                        if not hist.empty:
                            close_price = hist['Close'].dropna().iloc[-1]
                            actual_return_pct = (close_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0
                    except:
                        pass
                
                pnl = allocated_dollars * actual_return_pct
                daily_pnl[held_etf] = pnl
                settled_equity += (allocated_dollars + pnl)
                print(f"  [ORPHAN LIQUIDATED] {held_etf} returned ${allocated_dollars + pnl:.2f} to cash pile (PnL: ${pnl:+.2f}).")
                
                # Remove from holdings so the standard loop ignores it
                del holdings[held_etf]

        # 2. Settle yesterday's active trades
        for etf, df in scorecards.items():
            settlement_row = df.iloc[-2]
            
            if etf in holdings:
                item = holdings[etf]
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                actual_return_pct = settlement_row['Actual Daily Return %']
                
                if pd.notna(actual_return_pct):
                    # --- INTRA-DAY STOP-LOSS LOGIC & EXACT PNL RECALCULATION ---
                    purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                    if purchase_price > 0:
                        try:
                            from failover_downloader import download_ticker_with_failover
                            settle_date_str = settlement_row['Date']
                            if not isinstance(settle_date_str, str):
                                settle_date_str = settle_date_str.strftime('%Y-%m-%d')
                                
                            hist = download_ticker_with_failover(etf, start=settle_date_str)
                            if not hist.empty:
                                close_price = hist['Close'].iloc[0]
                                low_price = hist['Low'].iloc[0]
                                
                                # Overwrite the static scorecard return with the EXACT true return based on live purchase price
                                actual_return_pct = (close_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0
                                
                                # --- DYNAMIC VIX STOP-LOSS LOGIC ---
                                dynamic_stop_loss = -0.03 # ETF default
                                vix_high = 0.0
                                if not global_vix_hist.empty:
                                    try:
                                        if settle_date_str in global_vix_hist.index.strftime('%Y-%m-%d'):
                                            vix_high = global_vix_hist[global_vix_hist.index.strftime('%Y-%m-%d') == settle_date_str]['High'].iloc[0]
                                        else:
                                            vix_high = global_vix_hist['High'].iloc[-1]
                                            
                                        if persona_name == "Conservative":
                                            dynamic_stop_loss = -0.005 if vix_high > 35.0 else (-0.015 if vix_high > 25.0 else -0.025)
                                        elif persona_name == "Neutral":
                                            dynamic_stop_loss = -0.010 if vix_high > 35.0 else (-0.020 if vix_high > 25.0 else -0.030)
                                        else: # BallsForBrains / Dynamic
                                            dynamic_stop_loss = -0.020 if vix_high > 35.0 else (-0.030 if vix_high > 25.0 else -0.040)
                                    except: pass
                                
                                intraday_drop = (low_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0
                                if intraday_drop <= dynamic_stop_loss:
                                    panic_str = f"(VIX {vix_high:.1f})" if vix_high > 0 else ""
                                    print(f"  [STOP-LOSS TRIGGERED] {etf} dropped {intraday_drop*100:.1f}% intraday! Intercepting loss at {dynamic_stop_loss*100:.1f}% {panic_str}")
                                    actual_return_pct = dynamic_stop_loss
                        except:
                            pass
                    # -------------------------------------------------------------
                    
                    pnl = allocated_dollars * actual_return_pct
                    daily_pnl[etf] = pnl
                    settled_equity += (allocated_dollars + pnl)
                else:
                    daily_pnl[etf] = 0.0
                    settled_equity += allocated_dollars
                    
        # --- ZOMBIE FAILSAFE LOGIC ---
        for held_ticker, item in holdings.items():
            if held_ticker not in scorecards.keys() and held_ticker not in daily_pnl:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                
                try:
                    import yfinance as yf
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
                        print(f"  [ZOMBIE FAILSAFE TRIGGERED] {held_ticker} returned empty data (Likely delisted or Ticker Change)!")
                        print(f"  Force liquidating {held_ticker} at purchase price. Returning ${allocated_dollars:.2f} to Cash.")
                        daily_pnl[held_ticker] = 0.0
                        settled_equity += allocated_dollars
                except Exception as e:
                    print(f"  [ZOMBIE FAILSAFE ERROR] Could not verify {held_ticker}: {e}. Returning capital to Cash.")
                    daily_pnl[held_ticker] = 0.0
                    settled_equity += allocated_dollars
        # -----------------------------
                    
        # --- VIX MACRO-CAP LOGIC ---
        vix_multiplier = 1.0
        vix_triggered = False
        try:
            import yfinance as yf
            vix_hist = yf.Ticker('^VIX').history(period='5d')
            if not vix_hist.empty:
                latest_vix = vix_hist['Close'].dropna().iloc[-1]
                if latest_vix > 30.0:
                    vix_multiplier = 0.0
                    vix_triggered = True
                    print(f"  [VIX MACRO-CAP TRIGGERED] Extreme Market Panic (^VIX = {latest_vix:.2f} > 30.0). Kelly -> 0.0x")
                    print("  Halting all active trades. Retreating to 100% Cash.")
                elif latest_vix > 25.0:
                    vix_multiplier = 0.5
                    print(f"  [VIX MACRO-CAP] High Risk (^VIX = {latest_vix:.2f}). Kelly -> 0.5x")
                elif latest_vix > 20.0:
                    vix_multiplier = 0.8
                    print(f"  [VIX MACRO-CAP] Elevated Risk (^VIX = {latest_vix:.2f}). Kelly -> 0.8x")
        except:
            pass
        # ---------------------------
        
        # 3. Calculate new allocations
        new_holdings = {}
        new_cash = settled_equity
        available_capital = settled_equity
        
        # --- ETF HOLDING PROTECTION: FREEZE QUARANTINED POSITIONS ---
        for held_etf, item in holdings.items():
            if held_etf in scorecards and held_etf not in new_holdings:
                try:
                    df_t = scorecards[held_etf]
                    if not df_t.empty:
                        last_r = df_t.iloc[-1]
                        status = str(last_r.get('Retraining_Status', ''))
                        
                        is_frozen = ("QUARANTINED" in status)
                        
                        if is_frozen:
                            allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                            purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                            held_units = int(item.get("units", 0)) if isinstance(item, dict) else 0
                            
                            current_value = allocated_dollars + daily_pnl.get(held_etf, 0.0)
                            print(f"  [ETF HOLDING PROTECTION] Freezing existing position in {held_etf} due to PyMC Engine Crash fallback.")
                            new_holdings[held_etf] = {"dollars": current_value, "price": purchase_price, "units": held_units}
                            new_cash -= current_value
                            available_capital -= current_value
                except Exception as e:
                    print(f"  Error checking ETF holding protection for {held_etf}: {e}")
        
        import yfinance as yf
        for etf, df in scorecards.items():
            pending_row = df.iloc[-1]
            prob = pending_row['Bayesian Probability P(UP)']
            exp_ret = pending_row['Expected Return %']
            exp_vol = pending_row['Expected Risk (Volatility) %']
            
            if prob > config['threshold']:
                if vix_multiplier == 0.0:
                    print(f"  [BLOCKED BY VIX] Skipped {etf} (P={prob*100:.1f}%).")
                    continue
                    
                if available_capital <= 0:
                    print(f"  [SAFETY STOP] Cannot buy {etf} - Account depleted!")
                    continue
                    
                raw_kelly = calculate_kelly_fraction(prob, exp_ret, exp_vol)
                applied_kelly = raw_kelly * config['kelly_multiplier'] * vix_multiplier
                final_allocation_pct = min(applied_kelly, config['max_alloc'])
                
                if final_allocation_pct > 0:
                    raw_alloc_dollars = available_capital * final_allocation_pct
                    if raw_alloc_dollars > new_cash:
                        raw_alloc_dollars = new_cash
                        
                    try:
                        import yfinance as yf
                        from failover_downloader import download_ticker_with_failover
                        
                        # Use exact historical data up to the target simulation date to prevent future leakage
                        hist = download_ticker_with_failover(etf, start=(pd.to_datetime(target_date_for_ledger) - pd.Timedelta(days=5)).strftime('%Y-%m-%d'))
                        hist = hist[hist.index <= pd.to_datetime(target_date_for_ledger)]
                        
                        if not hist.empty:
                            latest_price = hist['Close'].dropna().iloc[-1]
                            units = int(raw_alloc_dollars // latest_price)
                            alloc_dollars = units * latest_price
                        else:
                            units = 0
                            latest_price = 0
                            alloc_dollars = 0.0
                    except:
                        units = 0; latest_price = 0; alloc_dollars = 0.0
                        
                    if alloc_dollars > 0:
                        new_holdings[etf] = {"dollars": alloc_dollars, "units": units, "price": latest_price}
                        new_cash -= alloc_dollars
                        if units > 0:
                            print(f"  [BUY] {etf} | {units} units @ ${latest_price:.2f} = ${alloc_dollars:.2f} (P={prob*100:.1f}%)")
                        else:
                            print(f"  [BUY] {etf} | Alloc: ${alloc_dollars:.2f} (P={prob*100:.1f}%)")
        
        if not new_holdings:
            print("  [HOLD] Sitting safely in Cash.")
            
        print(f"  End of Day Equity: ${settled_equity:.2f} (Cash: ${new_cash:.2f})\n")
        
        # 4. Save intended state to Pending Orders for Intraday Execution
        intended_state = {
            "Persona": f"ETF_{persona_name}",
            "Date": target_date_for_ledger,
            "Target_Cash": round(new_cash, 2),
            "Target_Total_Equity": round(settled_equity, 2),
            "Target_Holdings": {k: {"dollars": round(v["dollars"], 2), "units": v["units"], "price": v["price"]} for k, v in new_holdings.items()},
            "Daily_PnL_JSON": {k: round(v, 2) for k, v in daily_pnl.items()},
            "Executed_Intraday_Trades": {}
        }
        
        database_manager.save_pending_order(
            persona=f"ETF_{persona_name}",
            date=intended_state["Date"],
            target_cash=intended_state["Target_Cash"],
            target_equity=intended_state["Target_Total_Equity"],
            target_holdings=intended_state["Target_Holdings"],
            daily_pnl=intended_state["Daily_PnL_JSON"],
            executed_trades=intended_state["Executed_Intraday_Trades"]
        )
            
        print(f"  [STAGING MODE] Delegated execution for ETF_{persona_name} to Intraday Tracker. Saved to Pending_Orders.json")
        
        final_equities[persona_name] = settled_equity

    print("=== LIVE ETF LEADERBOARD ===")
    sorted_equities = sorted(final_equities.items(), key=lambda x: x[1], reverse=True)
    rank = 1
    for name, eq in sorted_equities:
        profit = eq - 10000.0
        print(f"#{rank} {name.ljust(15)} : ${eq:,.2f}  (Profit: ${profit:+,.2f})")
        rank += 1
        
if __name__ == '__main__':
    run_etf_virtual_broker()
    os._exit(0)
