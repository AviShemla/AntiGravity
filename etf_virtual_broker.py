import pandas as pd
import numpy as np
import os
import json
import database_manager

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
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
    
    # SOURCE OF TRUTH: Turso DB etf_scorecards_master
    try:
        import sys
        if len(sys.argv) > 2 and "Capital" not in sys.argv[2]:
            target_date_for_ledger = sys.argv[2]
            scorecard_date = target_date_for_ledger
        else:
            import pandas_market_calendars as mcal
            nyse = mcal.get_calendar('NYSE')
            now = pd.Timestamp.now(tz='America/New_York')
            date_res = database_manager.execute_query(
                "SELECT MAX(date) as d FROM etf_scorecards_master WHERE persona='ETF_BallsForBrains'"
            )
            scorecard_date = date_res.iloc[0][0] if not date_res.empty else now.strftime('%Y-%m-%d')
            target_date_for_ledger = scorecard_date
    except Exception as e:
        print(f"Date calculation error: {e}")
        target_date_for_ledger = pd.Timestamp.now().strftime('%Y-%m-%d')
        scorecard_date = target_date_for_ledger

    # Load all ETF scorecard rows from DB up to target date
    df_scorecard_all = database_manager.execute_query(
        "SELECT ticker, persona, date, prob, expected_return, expected_risk, kelly_allocation, "
        "recommendation, broker_override_note, retraining_status, actual_return "
        "FROM etf_scorecards_master WHERE persona LIKE 'ETF_%' AND date <= ? ORDER BY date DESC",
        [scorecard_date]
    )
    if df_scorecard_all.empty:
        print(f"[ABORT] No ETF scorecard data in DB for date <= {scorecard_date}")
        return

    ticker_universe = df_scorecard_all[df_scorecard_all['date'] == df_scorecard_all['date'].max()]['ticker'].unique().tolist()
    print(f"ETF Ticker universe from DB ({scorecard_date}): {ticker_universe}")

    def get_etf_scorecard_row(ticker, target_date, persona):
        sub = df_scorecard_all[
            (df_scorecard_all['ticker'] == ticker) &
            (df_scorecard_all['persona'] == persona) &
            (df_scorecard_all['date'] <= target_date)
        ]
        if sub.empty:
            return None
        return sub.sort_values('date').iloc[-1]

    final_equities = {}
    
    # --- DYNAMIC ALLOCATOR (SHARPE RATIO) — reads from Turso DB ---
    dynamic_winner = "Neutral"
    try:
        sharpe_scores = {}
        for p in ["Conservative", "Neutral", "BallsForBrains"]:
            df_p = database_manager.get_ledger(f"ETF_{p}")
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
        full_persona = f"ETF_{persona_name}"
        print(f"--- Persona: {full_persona.upper()} ---")

        ledger = database_manager.get_ledger(full_persona)

        if ledger.empty:
            ledger = pd.DataFrame([{
                'Date': '2026-04-22',
                'Cash': 10000.0,
                'Total_Equity': 10000.0,
                'Holdings_JSON': '{}',
                'Daily_PnL_JSON': '{}'
            }])
        
        if not ledger.empty and str(target_date_for_ledger) == str(ledger['Date'].iloc[-1]):
            print(f"  [IDEMPOTENT OVERWRITE] Re-executing for date {target_date_for_ledger}.")
            tickers_today = df_scorecard_all[
                (df_scorecard_all['date'] == scorecard_date) &
                (df_scorecard_all['persona'] == full_persona)
            ]['ticker'].tolist()
            if len(tickers_today) == 0:
                print(f"  [INTEGRITY FAILURE] No scorecard rows in DB for {scorecard_date}/{full_persona}. Aborting.")
                final_equities[persona_name] = float(ledger['Total_Equity'].iloc[-1])
                continue
            else:
                print(f"  [INTEGRITY PASSED] {len(tickers_today)} ETF tickers in DB for today. Proceeding.")
            
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
        
        # 1.5 Settle Orphaned Trades (ETFs dropped from the Dynamic Top list)
        for held_etf, item in list(holdings.items()):
            if held_etf not in ticker_universe:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                print(f"  [ORPHAN LIQUIDATION] {held_etf} dropped from Top rankings! Liquidating position to free capital...")

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
                del holdings[held_etf]

        # 2. Settle yesterday's active trades from Turso DB
        for etf in ticker_universe:
            sc_row = get_etf_scorecard_row(etf, target_date_for_ledger, full_persona)
            if sc_row is None or len(df_scorecard_all[
                (df_scorecard_all['ticker'] == etf) &
                (df_scorecard_all['persona'] == full_persona) &
                (df_scorecard_all['date'] <= target_date_for_ledger)
            ]) < 2:
                continue
            sub = df_scorecard_all[
                (df_scorecard_all['ticker'] == etf) &
                (df_scorecard_all['persona'] == full_persona) &
                (df_scorecard_all['date'] <= target_date_for_ledger)
            ].sort_values('date')
            settlement_row = sub.iloc[-2]

            if etf in holdings:
                item = holdings[etf]
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                actual_return_pct = settlement_row.get('actual_return', None)
                
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
            if held_ticker not in ticker_universe and held_ticker not in daily_pnl:
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
        
        # --- ETF HOLDING PROTECTION: FREEZE QUARANTINED POSITIONS — from Turso DB ---
        for held_etf, item in holdings.items():
            if held_etf in ticker_universe and held_etf not in new_holdings:
                try:
                    sc_row = get_etf_scorecard_row(held_etf, target_date_for_ledger, full_persona)
                    if sc_row is not None:
                        status = str(sc_row.get('retraining_status', '') or '')
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
        for etf in ticker_universe:
            if etf in new_holdings:
                continue
            sc_row = get_etf_scorecard_row(etf, target_date_for_ledger, full_persona)
            if sc_row is None:
                continue
            prob = float(sc_row.get('prob', 0) or 0)
            exp_ret = float(sc_row.get('expected_return', 0) or 0)
            exp_vol = float(sc_row.get('expected_risk', 0) or 0)
            status = str(sc_row.get('retraining_status', 'Stable') or 'Stable')
            if 'SUSPENDED' in status:
                continue
            
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
    import sys; sys.stdout.flush(); os._exit(0)
