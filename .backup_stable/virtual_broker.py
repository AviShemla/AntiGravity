import pandas as pd
import numpy as np
import os
import json
import sys
from blacklist_engine import get_blacklisted_tickers

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
        "kelly_multiplier": 1.0,
        "max_alloc": 0.10,
        "flat_fallback": 0.20,
        "ignore_kelly": True
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
        
        ledger_path = os.path.join(BASE_DIR, f'Capital_Ledger_{persona_name}.csv')
        
        # 1. Initialize or load ledger
        if not os.path.exists(ledger_path):
            ledger = pd.DataFrame([{
                'Date': '2025-05-01',
                'Cash': 10000.0,
                'Total_Equity': 10000.0,
                'Holdings_JSON': '{}',
                'Daily_PnL_JSON': '{}'
            }])
            ledger.to_csv(ledger_path, index=False)
        
        ledger = pd.read_csv(ledger_path)
        
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
                print(f"Error: Target date {target_date_for_ledger} not found in scorecard.")
                return
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
                'Date': '2025-05-01', 'Cash': 10000.0, 'Total_Equity': 10000.0, 
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
        
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet, skiprows=2)
            sheet_date_col = 'date' if 'date' in df.columns else 'Date'
            df = df[pd.to_datetime(df[sheet_date_col]) <= pd.to_datetime(target_date_for_ledger)]
            if len(df) < 2: continue
            
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
                    # --- INTRA-DAY STOP-LOSS LOGIC & EXACT PNL RECALCULATION ---
                    purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                    if purchase_price > 0:
                        try:
                            import yfinance as yf
                            settle_date_str = settlement_row[sheet_date_col].strftime('%Y-%m-%d')
                            hist = yf.Ticker(sheet).history(start=settle_date_str, end=target_date_for_ledger)
                            if not hist.empty:
                                close_price = hist['Close'].iloc[0]
                                low_price = hist['Low'].iloc[0]
                                
                                # Overwrite the static scorecard return with the EXACT true return based on live purchase price
                                actual_return_pct = (close_price - purchase_price) / purchase_price
                                
                                intraday_drop = (low_price - purchase_price) / purchase_price
                                if intraday_drop <= -0.05:
                                    print(f"  [STOP-LOSS TRIGGERED] {sheet} dropped {intraday_drop*100:.1f}% intraday! Intercepting loss at -5.0%.")
                                    actual_return_pct = -0.05
                        except:
                            pass
                    # -------------------------------------------------------------
                    
                    pnl = allocated_dollars * actual_return_pct
                    daily_pnl[sheet] = pnl
                    settled_equity += (allocated_dollars + pnl)
                else:
                    daily_pnl[sheet] = 0.0
                    settled_equity += allocated_dollars
                    
        # --- ZOMBIE FAILSAFE LOGIC ---
        for held_ticker, item in holdings.items():
            if held_ticker not in xls.sheet_names:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                
                try:
                    import yfinance as yf
                    hist = yf.Ticker(held_ticker).history(period='2d')
                    if not hist.empty and purchase_price > 0:
                        latest_price = hist['Close'].iloc[-1]
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
                    
        # --- VIX MACRO-CAP LOGIC ---
        vix_multiplier = 1.0
        vix_triggered = False
        try:
            import yfinance as yf
            vix_hist = yf.Ticker('^VIX').history(period='5d')
            if not vix_hist.empty:
                latest_vix = vix_hist['Close'].iloc[-1]
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
                    print(f"  [QUARANTINE] Retaining existing position in {held_ticker} without allocating new capital.")
                    new_holdings[held_ticker] = {"dollars": allocated_dollars, "price": purchase_price}
                    new_cash -= allocated_dollars
                    available_capital -= allocated_dollars
                    
        # --- HOLDING PROTECTION: FREEZE QUARANTINED OR V1-DEGRADED POSITIONS ---
        for held_ticker, item in holdings.items():
            if held_ticker in xls.sheet_names and held_ticker not in new_holdings:
                try:
                    df_t = pd.read_excel(xls, sheet_name=held_ticker, skiprows=2)
                    if not df_t.empty:
                        last_r = df_t.iloc[-1]
                        override_note = str(last_r.get('Broker Override Note', ''))
                        status = str(last_r.get('Retraining_Status', ''))
                        
                        is_frozen = ("QUARANTINED" in status) or ("Held Position Frozen" in override_note)
                        
                        if is_frozen:
                            allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                            purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                            if allocated_dollars > 0:
                                print(f"  [HOLDING PROTECTION] Freezing existing position in {held_ticker} due to data/model fallback.")
                                new_holdings[held_ticker] = {"dollars": allocated_dollars, "price": purchase_price}
                                new_cash -= allocated_dollars
                                available_capital -= allocated_dollars
                except Exception as e:
                    print(f"  Error checking holding protection for {held_ticker}: {e}")
                    
        import yfinance as yf
        for sheet in xls.sheet_names:
            if sheet in new_holdings:
                continue
            if sheet in blacklisted:
                if sheet not in new_holdings:
                    print(f"  [BLACKLIST] Broker refused to allocate capital for {sheet} due to 3 autopsy strikes.")
                continue
                
            df = pd.read_excel(xls, sheet_name=sheet, skiprows=2)
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
                        # Fetch latest close price to calculate whole units
                        ticker_data = yf.Ticker(sheet).history(period='5d')
                        if not ticker_data.empty:
                            latest_price = ticker_data['Close'].iloc[-1]
                            units = int(raw_alloc_dollars // latest_price)
                            alloc_dollars = units * latest_price
                        else:
                            # Fallback if yfinance fails
                            units = 0
                            latest_price = 0
                            alloc_dollars = raw_alloc_dollars
                    except:
                        units = 0
                        latest_price = 0
                        alloc_dollars = raw_alloc_dollars
                        
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
            "Executed_Intraday_Trades": {},
            "Ledger_Path": ledger_path
        }
        
        pending_orders_path = os.path.join(BASE_DIR, 'Pending_Orders.json')
        
        if os.path.exists(pending_orders_path):
            with open(pending_orders_path, 'r') as f:
                try:
                    pending_orders = json.load(f)
                except:
                    pending_orders = {}
        else:
            pending_orders = {}
            
        pending_orders[persona_name] = intended_state
        
        with open(pending_orders_path, 'w') as f:
            json.dump(pending_orders, f, indent=4)
            
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
