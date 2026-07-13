import pandas as pd
import numpy as np
import os
import json
import sys
from blacklist_engine import get_blacklisted_tickers
import database_manager

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
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
    target_excel = os.path.join(BASE_DIR, 'All_ETFs_Scorecard.xlsx') if len(sys.argv) > 1 and sys.argv[1] == "ETF" else EXCEL_PATH
    try:
        xls = pd.ExcelFile(target_excel)
    except Exception as e:
        print(f"Could not load scorecard: {e}")
        return

    final_equities = {}
    
    # --- DYNAMIC ALLOCATOR (SHARPE RATIO) ---
    dynamic_winner = "Neutral"
    try:
        sharpe_scores = {}
        for p in ["Conservative", "Neutral", "BallsForBrains"]:
            p_ledger = os.path.join(BASE_DIR, f'Capital_Ledger_{p}.csv')
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
        print(f"Rules: Buy if P > {config['threshold']:.2f} | {config['kelly_multiplier']}x Kelly | Max {config['max_alloc']*100}% per stock")
        
        # 1. Initialize or load ledger
        ledger = database_manager.get_ledger(persona_name)
        if ledger.empty:
            ledger = pd.DataFrame([{
                'Date': '2026-04-22',
                'Cash': 10000.0,
                'Total_Equity': 10000.0,
                'Holdings_JSON': '{}',
                'Daily_PnL_JSON': '{}'
            }])
        
        # Extract target date to check for double-runs
        first_sheet = xls.sheet_names[0]
        df_first = pd.read_excel(xls, sheet_name=first_sheet, skiprows=2)
        
        date_col = 'date' if 'date' in df_first.columns else 'Date'
        
        if df_first.empty:
            print("  [SAFETY STOP] Scorecard is completely empty. Rolling over ledger with 0 PnL.")
            target_date_for_ledger = pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d')
        elif len(sys.argv) > 2 and "Capital" not in sys.argv[2]:
            target_date_for_ledger = sys.argv[2]
            # Verify the date exists in the scorecard
            if not (pd.to_datetime(df_first[date_col]) == pd.to_datetime(target_date_for_ledger)).any():
                print(f"  [WARNING] Target date {target_date_for_ledger} not found in first sheet (likely quarantined). Proceeding cautiously...")
        else:
            target_date_for_ledger = df_first.iloc[-1][date_col].strftime('%Y-%m-%d')
        
        if not ledger.empty and target_date_for_ledger == str(ledger['Date'].iloc[-1]):
            print(f"  [IDEMPOTENT OVERWRITE] Re-executing for date {target_date_for_ledger}. Checking Scorecard Integrity...")
            empty_count = 0
            for test_sheet in xls.sheet_names:
                df_test = pd.read_excel(xls, sheet_name=test_sheet, skiprows=2)
                if df_test.empty or len(df_test) < 2:
                    empty_count += 1
            if empty_count > len(xls.sheet_names) * 0.1:
                print(f"  [INTEGRITY FAILURE] Scorecard is highly corrupted ({empty_count} empty sheets). Aborting overwrite to protect ledger.")
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
        
        # 2. Settle yesterday's trades based on actual returns
        settled_equity = current_cash
        daily_pnl = {}
        
        skip_sheets = set()
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet, skiprows=2)
            sheet_date_col = 'date' if 'date' in df.columns else 'Date'
            df = df[pd.to_datetime(df[sheet_date_col]) <= pd.to_datetime(target_date_for_ledger)]
            if len(df) < 2:
                skip_sheets.add(sheet)
                continue
            
            settlement_row = df.iloc[-2]
            pending_row = df.iloc[-1]
            
            if sheet in holdings:
                item = holdings[sheet]
                if isinstance(item, dict):
                    allocated_dollars = item.get("dollars", 0.0)
                else:
                    allocated_dollars = float(item)
                    
                ret_col = 'actual value daily return %' if 'actual value daily return %' in settlement_row else 'Actual Daily Return %'
                actual_return_pct = settlement_row[ret_col]
                
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
            if held_ticker not in xls.sheet_names or held_ticker in skip_sheets:
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
                    
        # --- HOLDING PROTECTION: FREEZE QUARANTINED OR V1-DEGRADED POSITIONS ---
        for held_ticker, item in holdings.items():
            if held_ticker in xls.sheet_names and held_ticker not in new_holdings:
                try:
                    df_t = pd.read_excel(xls, sheet_name=held_ticker, skiprows=2)
                    if not df_t.empty:
                        last_r = df_t.iloc[-1]
                        override_note = str(last_r.get('Broker Override Note', ''))
                        status = str(last_r.get('Retraining_Status', ''))
                        
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
        
        for sheet in xls.sheet_names:
            if sheet in new_holdings:
                continue
            if sheet in blacklisted:
                if sheet not in new_holdings:
                    print(f"  [BLACKLIST] Broker refused to allocate capital for {sheet} due to 3 autopsy strikes.")
                continue
                
            # --- SECTOR GRAVITY FILTER (DISABLED) ---
            # parent_etf = stock_to_etf.get(sheet)
            # if parent_etf and gravity_map.get(parent_etf) is False:
            #     print(f"  [SECTOR GRAVITY] Broker blocked {sheet} because its parent sector ({parent_etf}) is bleeding momentum.")
            #     continue
                
            df = pd.read_excel(xls, sheet_name=sheet, skiprows=2)
            sheet_date_col = 'date' if 'date' in df.columns else 'Date'
            df = df[pd.to_datetime(df[sheet_date_col]) <= pd.to_datetime(target_date_for_ledger)]
            if df.empty: continue
            pending_row = df.iloc[-1]
            
            prob = pending_row['Bayesian Probability P(UP)']
            exp_ret = pending_row['Expected Return %']
            exp_vol = pending_row['Expected Risk (Volatility) %']
            status = pending_row.get('Retraining_Status', 'Stable')
            
            if "SUSPENDED" in str(status): continue
                
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
                        else:
                            # Fallback if yfinance fails
                            units = 0
                            latest_price = 0
                            alloc_dollars = 0.0
                    except:
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
        
        # 4. Save intended state to Pending Orders
        intended_state = {
            "Persona": persona_name,
            "Date": target_date_for_ledger,
            "Target_Cash": round(new_cash, 2),
            "Target_Total_Equity": round(settled_equity, 2),
            "Target_Holdings": {k: {"dollars": round(v["dollars"], 2), "units": v["units"], "price": v["price"]} for k, v in new_holdings.items()},
            "Daily_PnL_JSON": {k: round(v, 2) for k, v in daily_pnl.items()},
            "Executed_Intraday_Trades": {}
        }
        
        database_manager.save_pending_order(
            persona=persona_name,
            date=intended_state["Date"],
            target_cash=intended_state["Target_Cash"],
            target_equity=intended_state["Target_Total_Equity"],
            target_holdings=intended_state["Target_Holdings"],
            daily_pnl=intended_state["Daily_PnL_JSON"],
            executed_trades=intended_state["Executed_Intraday_Trades"]
        )
            
        print(f"  [STAGING MODE] Delegated execution for {persona_name} to Intraday Tracker. Saved to Pending_Orders.json")
        
        final_equities[persona_name] = settled_equity

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
