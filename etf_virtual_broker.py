import pandas as pd
import numpy as np
import os
import json
import sys
import argparse
import database_manager
import oracle_lineage_core

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
try:
    with open(os.path.join(BASE_DIR, 'Dynamic_Target_ETFs.json'), 'r') as f:
        TARGET_ETFS = json.load(f)
except:
    TARGET_ETFS = ["XLK"]

PERSONAS = {
    "Conservative": {
        "threshold": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_Conservative"]["prob_threshold"],
        "kelly_multiplier": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_Conservative"]["kelly_multiplier"],
        "max_alloc": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_Conservative"]["max_cap"],
    },
    "Neutral": {
        "threshold": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_Neutral"]["prob_threshold"],
        "kelly_multiplier": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_Neutral"]["kelly_multiplier"],
        "max_alloc": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_Neutral"]["max_cap"],
    },
    "BallsForBrains": {
        "threshold": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_BallsForBrains"]["prob_threshold"],
        "kelly_multiplier": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_BallsForBrains"]["kelly_multiplier"],
        "max_alloc": oracle_lineage_core.ETF_PERSONA_CONFIG["ETF_BallsForBrains"]["max_cap"],
    },
}

def calculate_kelly_fraction(prob, expected_return, expected_volatility):
    if expected_return <= 0 or expected_volatility <= 0:
        return 0.0
    R = expected_return / expected_volatility
    W = prob
    kelly_pct = W - ((1 - W) / R)
    return max(0.0, kelly_pct)

def _resolve_target_date():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--target-date", type=str, default=None)
    known, unknown = parser.parse_known_args()
    if known.target_date:
        return str(known.target_date)[:10]
    for arg in unknown:
        if "Capital" not in arg and not arg.startswith("-"):
            return str(arg)[:10]
    return None

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
        cli_date = _resolve_target_date()
        if cli_date:
            target_date_for_ledger = cli_date
            scorecard_date = cli_date
        else:
            now = pd.Timestamp.now(tz='America/New_York')
            date_res = database_manager.execute_query(
                "SELECT MAX(date) as d FROM etf_scorecards_master WHERE persona='ETF_BallsForBrains'"
            )
            scorecard_date = str(date_res.iloc[0][0])[:10] if not date_res.empty and date_res.iloc[0][0] else now.strftime('%Y-%m-%d')
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

    try:
        oracle_lineage_core.init_lineage_tables()
    except Exception:
        pass
    
    for persona_name, config in runtime_personas.items():
        full_persona = f"ETF_{persona_name}"
        eval_persona_name = f"ETF_{dynamic_winner}" if persona_name == "Dynamic" else full_persona
        print(f"--- Persona: {full_persona.upper()} (Rule Profile: {eval_persona_name}) ---")

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
        holdings = json.loads(last_state['Holdings_JSON']) if isinstance(last_state['Holdings_JSON'], str) else last_state['Holdings_JSON']
        
        settled_equity = current_cash
        daily_pnl = {}
        
        # 1.5 Settle Orphaned Trades (ETFs dropped from the Dynamic Top list) using single-day return
        for held_etf, item in list(holdings.items()):
            if held_etf == "Cash":
                continue
            if held_etf not in ticker_universe:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                print(f"  [ORPHAN LIQUIDATION] {held_etf} dropped from Top rankings! Liquidating position to free capital...")

                actual_return_pct = 0.0
                if purchase_price > 0:
                    try:
                        from failover_downloader import download_ticker_with_failover
                        hist = download_ticker_with_failover(held_etf, start=(pd.to_datetime(target_date_for_ledger) - pd.Timedelta(days=5)).strftime('%Y-%m-%d'))
                        hist = hist[hist.index <= pd.to_datetime(target_date_for_ledger)]
                        if not hist.empty and len(hist['Close'].dropna()) >= 2:
                            close_price = float(hist['Close'].dropna().iloc[-1])
                            prev_price = float(hist['Close'].dropna().iloc[-2])
                            actual_return_pct = (close_price - prev_price) / prev_price if prev_price > 0 else 0.0
                    except Exception:
                        pass

                pnl = allocated_dollars * actual_return_pct
                daily_pnl[held_etf] = pnl
                settled_equity += (allocated_dollars + pnl)
                print(f"  [ORPHAN LIQUIDATED] {held_etf} returned ${allocated_dollars + pnl:.2f} to cash pile (PnL: ${pnl:+.2f}).")
                del holdings[held_etf]

        # 2. Settle yesterday's active trades from Turso DB
        for etf in ticker_universe:
            sub = df_scorecard_all[
                (df_scorecard_all['ticker'] == etf) &
                (df_scorecard_all['persona'] == full_persona) &
                (df_scorecard_all['date'] <= target_date_for_ledger)
            ].sort_values('date')
            if len(sub) < 2:
                continue
            settlement_row = sub.iloc[-2]

            if etf in holdings:
                item = holdings[etf]
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                actual_return_pct = settlement_row.get('actual_return', None)
                
                if pd.notna(actual_return_pct):
                    actual_return_pct = float(actual_return_pct)
                    # --- INTRA-DAY STOP-LOSS ONLY (Bug #2 Fix: NEVER overwrite single-day scorecard return with cumulative return) ---
                    purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                    if purchase_price > 0:
                        try:
                            from failover_downloader import download_ticker_with_failover
                            settle_date_str = settlement_row['date']
                            if not isinstance(settle_date_str, str):
                                settle_date_str = pd.to_datetime(settle_date_str).strftime('%Y-%m-%d')
                                
                            hist = download_ticker_with_failover(etf, start=settle_date_str)
                            if not hist.empty:
                                low_price = float(hist['Low'].iloc[0])
                                
                                dynamic_stop_loss = -0.025
                                vix_high = 0.0
                                if not global_vix_hist.empty:
                                    try:
                                        if settle_date_str in global_vix_hist.index.strftime('%Y-%m-%d'):
                                            vix_high = float(global_vix_hist[global_vix_hist.index.strftime('%Y-%m-%d') == settle_date_str]['High'].iloc[0])
                                        else:
                                            vix_high = float(global_vix_hist['High'].iloc[-1])
                                            
                                        if persona_name == "Conservative":
                                            dynamic_stop_loss = -0.005 if vix_high > 35.0 else (-0.015 if vix_high > 25.0 else -0.025)
                                        elif persona_name == "Neutral":
                                            dynamic_stop_loss = -0.010 if vix_high > 35.0 else (-0.020 if vix_high > 25.0 else -0.030)
                                        else:
                                            dynamic_stop_loss = -0.020 if vix_high > 35.0 else (-0.030 if vix_high > 25.0 else -0.040)
                                    except Exception:
                                        pass
                                
                                intraday_drop = (low_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0
                                if intraday_drop <= dynamic_stop_loss:
                                    panic_str = f"(VIX {vix_high:.1f})" if vix_high > 0 else ""
                                    print(f"  [STOP-LOSS TRIGGERED] {etf} dropped {intraday_drop*100:.1f}% intraday! Intercepting loss at {dynamic_stop_loss*100:.1f}% {panic_str}")
                                    actual_return_pct = dynamic_stop_loss
                        except Exception:
                            pass
                    
                    pnl = allocated_dollars * actual_return_pct
                    daily_pnl[etf] = pnl
                    settled_equity += (allocated_dollars + pnl)
                else:
                    daily_pnl[etf] = 0.0
                    settled_equity += allocated_dollars
                    
        # --- ZOMBIE FAILSAFE LOGIC ---
        for held_ticker, item in holdings.items():
            if held_ticker == "Cash":
                continue
            if held_ticker not in ticker_universe and held_ticker not in daily_pnl:
                allocated_dollars = float(item.get("dollars", 0.0)) if isinstance(item, dict) else float(item)
                purchase_price = float(item.get("price", 0.0)) if isinstance(item, dict) else 0.0
                
                try:
                    from failover_downloader import download_ticker_with_failover
                    hist = download_ticker_with_failover(held_ticker, start=(pd.to_datetime(target_date_for_ledger) - pd.Timedelta(days=5)).strftime('%Y-%m-%d'))
                    hist = hist[hist.index <= pd.to_datetime(target_date_for_ledger)]
                    
                    if not hist.empty and purchase_price > 0 and len(hist['Close'].dropna()) >= 2:
                        latest_price = float(hist['Close'].dropna().iloc[-1])
                        prev_price = float(hist['Close'].dropna().iloc[-2])
                        actual_return_pct = (latest_price - prev_price) / prev_price if prev_price > 0 else 0.0
                        pnl = allocated_dollars * actual_return_pct
                        daily_pnl[held_ticker] = pnl
                        settled_equity += (allocated_dollars + pnl)
                        print(f"  [ZOMBIE RECOVERED] {held_ticker} active (Network glitch). Settled via single-day emergency fetch. PnL: ${pnl:.2f}")
                    else:
                        print(f"  [ZOMBIE FAILSAFE TRIGGERED] {held_ticker} returned empty data! Returning ${allocated_dollars:.2f} to Cash.")
                        daily_pnl[held_ticker] = 0.0
                        settled_equity += allocated_dollars
                except Exception as e:
                    print(f"  [ZOMBIE FAILSAFE ERROR] Could not verify {held_ticker}: {e}. Returning capital to Cash.")
                    daily_pnl[held_ticker] = 0.0
                    settled_equity += allocated_dollars

        # Enforce strict inter-day continuity: settled_equity == total_equity + sum(daily_pnl)
        is_cont, expected_settled_eq, _ = database_manager.verify_ledger_continuity(
            full_persona, target_date_for_ledger, total_equity, settled_equity, daily_pnl
        )
        if not is_cont:
            settled_equity = expected_settled_eq
                    
        # --- VIX MACRO-CAP LOGIC ---
        latest_vix = 18.0
        vix_path = os.path.join(BASE_DIR, "vix_score.json")
        try:
            if os.path.exists(vix_path):
                with open(vix_path, 'r') as f:
                    latest_vix = float(json.load(f).get("vix_value", 18.0))
            else:
                import yfinance as yf
                vix_hist = yf.Ticker('^VIX').history(period='5d')
                if not vix_hist.empty:
                    latest_vix = float(vix_hist['Close'].dropna().iloc[-1])
        except Exception:
            pass

        vix_multiplier = oracle_lineage_core.compute_vix_multiplier(eval_persona_name, latest_vix)
        if vix_multiplier == 0.0:
            print(f"  [VIX MACRO-CAP TRIGGERED] Extreme Market Panic (^VIX = {latest_vix:.2f}). Retreating to 100% Cash.")
        elif vix_multiplier < 1.0:
            print(f"  [VIX MACRO-CAP] (^VIX = {latest_vix:.2f}). Kelly VIX multiplier -> {vix_multiplier}x")
        
        # 3. Calculate new allocations
        new_holdings = {}
        new_cash = settled_equity
        available_capital = settled_equity
        
        # --- ETF HOLDING PROTECTION: FREEZE QUARANTINED POSITIONS ---
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
            if 'SUSPENDED' in status or 'QUARANTINED' in status:
                continue

            is_held_now = etf in holdings
            dec = oracle_lineage_core.evaluate_persona_decision(
                persona=eval_persona_name,
                prob_up=prob,
                expected_return_pct=exp_ret,
                expected_risk_pct=exp_vol,
                vix_val=latest_vix,
                is_currently_held=is_held_now
            )
            dec["persona"] = full_persona
            oracle_lineage_core.save_decision_lineage(
                dec, ticker=etf, target_date=target_date_for_ledger, asset_class="ETF"
            )
            
            final_allocation_pct = dec["applied_kelly"]
            if dec["recommendation"] in ("BUY", "HOLD_CARRYOVER") and final_allocation_pct > 0:
                if available_capital <= 0:
                    print(f"  [SAFETY STOP] Cannot buy {etf} - Account depleted!")
                    continue
                    
                raw_alloc_dollars = available_capital * final_allocation_pct
                if raw_alloc_dollars > new_cash:
                    raw_alloc_dollars = new_cash
                    
                try:
                    from failover_downloader import download_ticker_with_failover
                    hist = download_ticker_with_failover(etf, start=(pd.to_datetime(target_date_for_ledger) - pd.Timedelta(days=5)).strftime('%Y-%m-%d'))
                    hist = hist[hist.index <= pd.to_datetime(target_date_for_ledger)]
                    
                    if not hist.empty:
                        latest_price = float(hist['Close'].dropna().iloc[-1])
                        units = int(raw_alloc_dollars // latest_price)
                        alloc_dollars = units * latest_price

                        max_allowed_dollars = settled_equity * config['max_alloc']
                        if alloc_dollars > max_allowed_dollars:
                            alloc_dollars = max_allowed_dollars
                            units = int(alloc_dollars // latest_price)
                            alloc_dollars = units * latest_price
                    else:
                        units = 0
                        latest_price = 0.0
                        alloc_dollars = 0.0
                except Exception:
                    units = 0; latest_price = 0.0; alloc_dollars = 0.0
                    
                if alloc_dollars > 0:
                    new_holdings[etf] = {
                        "dollars": round(alloc_dollars, 2),
                        "units": int(units),
                        "price": round(latest_price, 4)
                    }
                    new_cash -= alloc_dollars
                    print(f"  [{dec['recommendation']}] {etf} | {units} units @ ${latest_price:.2f} = ${alloc_dollars:.2f} (P={prob*100:.1f}%, {dec['reason_code']})")
        
        if not new_holdings:
            print("  [HOLD] Sitting safely in Cash.")
            
        print(f"  End of Day Equity: ${settled_equity:.2f} (Cash: ${new_cash:.2f})\n")
        
        # 4. Save intended state to Pending Orders for Intraday Execution
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

        # Bug #3 Fix: For completed historical sessions, also persist settled state to capital_ledgers
        today_ny = pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d')
        if target_date_for_ledger < today_ny:
            database_manager.save_ledger_row(
                persona=full_persona,
                date=intended_state["Date"],
                cash=intended_state["Target_Cash"],
                total_equity=intended_state["Target_Total_Equity"],
                holdings_json=intended_state["Target_Holdings"],
                daily_pnl_json=intended_state["Daily_PnL_JSON"],
                intraday_status="Historical ETF Broker Settlement",
                engine_version=oracle_lineage_core.CODE_VERSION
            )
            
        print(f"  [STAGING MODE] Delegated execution for {full_persona} to Intraday Tracker. Saved to Pending_Orders.")
        
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
    sys.stdout.flush()
    os._exit(0)
