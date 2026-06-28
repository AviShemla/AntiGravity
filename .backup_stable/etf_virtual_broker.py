import pandas as pd
import numpy as np
import os
import json

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
try:
    with open(os.path.join(BASE_DIR, 'Dynamic_Target_ETFs.json'), 'r') as f:
        TARGET_ETFS = json.load(f)
except:
    TARGET_ETFS = ["XLK"]

PERSONAS = {
    "Conservative": {"threshold": 0.65, "kelly_multiplier": 0.25, "max_alloc": 0.10},
    "Neutral": {"threshold": 0.58, "kelly_multiplier": 0.50, "max_alloc": 0.10},
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
        
        ledger_path = os.path.join(BASE_DIR, f'ETF_Capital_Ledger_{persona_name}.csv')
        
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
        
        if not ledger.empty and str(target_date_for_ledger) == str(ledger['Date'].iloc[-1]):
            print(f"  [IDEMPOTENT OVERWRITE] Re-executing for date {target_date_for_ledger}. Checking Scorecard Integrity...")
            missing_count = len(TARGET_ETFS) - len(scorecards)
            if missing_count > len(TARGET_ETFS) * 0.1:
                print(f"  [INTEGRITY FAILURE] Scorecards are highly corrupted ({missing_count} missing/empty ETFs). Aborting overwrite to protect ledger.")
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
                        import yfinance as yf
                        hist = yf.Ticker(held_etf).history(period='5d')
                        if not hist.empty:
                            close_price = hist['Close'].iloc[-1]
                            actual_return_pct = (close_price - purchase_price) / purchase_price
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
                            import yfinance as yf
                            settle_date_str = settlement_row['Date']
                            if not isinstance(settle_date_str, str):
                                settle_date_str = settle_date_str.strftime('%Y-%m-%d')
                                
                            hist = yf.Ticker(etf).history(start=settle_date_str, end=target_date_for_ledger)
                            if not hist.empty:
                                close_price = hist['Close'].iloc[0]
                                low_price = hist['Low'].iloc[0]
                                
                                # Overwrite the static scorecard return with the EXACT true return based on live purchase price
                                actual_return_pct = (close_price - purchase_price) / purchase_price
                                
                                intraday_drop = (low_price - purchase_price) / purchase_price
                                if intraday_drop <= -0.03:
                                    print(f"  [STOP-LOSS TRIGGERED] {etf} dropped {intraday_drop*100:.1f}% intraday! Intercepting loss at -3.0%.")
                                    actual_return_pct = -0.03
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
                    hist = yf.Ticker(held_ticker).history(period='2d')
                    if not hist.empty and purchase_price > 0:
                        latest_price = hist['Close'].iloc[-1]
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
        
        # 3. Calculate new allocations
        new_holdings = {}
        new_cash = settled_equity
        available_capital = settled_equity
        
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
                        ticker_data = yf.Ticker(etf).history(period='5d')
                        if not ticker_data.empty:
                            latest_price = ticker_data['Close'].iloc[-1]
                            units = int(raw_alloc_dollars // latest_price)
                            alloc_dollars = units * latest_price
                        else:
                            units = 0; latest_price = 0; alloc_dollars = raw_alloc_dollars
                    except:
                        units = 0; latest_price = 0; alloc_dollars = raw_alloc_dollars
                        
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
            "Ledger_Path": ledger_path,
            "Persona": f"ETF_{persona_name}",
            "Date": target_date_for_ledger,
            "Target_Cash": round(new_cash, 2),
            "Target_Total_Equity": round(settled_equity, 2),
            "Target_Holdings": {k: {"dollars": round(v["dollars"], 2), "units": v["units"], "price": v["price"]} for k, v in new_holdings.items()},
            "Daily_PnL_JSON": {k: round(v, 2) for k, v in daily_pnl.items()},
            "Executed_Intraday_Trades": {}
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
            
        pending_orders[f"ETF_{persona_name}"] = intended_state
        
        with open(pending_orders_path, 'w') as f:
            json.dump(pending_orders, f, indent=4)
            
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
