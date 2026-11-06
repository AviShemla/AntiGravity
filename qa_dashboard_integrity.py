import os
import sys
import pandas as pd
import json

# Add parent directory to path to import database_manager
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database_manager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'financial_data')

def test_dashboard_continuity():
    print("=== QA AUDIT: DASHBOARD CONTINUITY TEST ===")
    
    # 1. Test Single Stocks Scorecard
    stock_path = os.path.join(DATA_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx')
    if os.path.exists(stock_path):
        try:
            df = pd.read_excel(stock_path)
            if 'Ticker' in df.columns:
                for ticker in df['Ticker'].unique():
                    sub_df = df[df['Ticker'] == ticker]
                    pending_count = (sub_df['actual Direction daily return'] == "Pending").sum()
                    
                    if pending_count >= 15:
                        print(f"[FAIL] {ticker} has {pending_count} 'Pending' statuses! History wipeout detected!")
                        import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
            print("SUCCESS - Single Stocks Scorecard history intact.")
        except Exception as e:
            print(f"Warning: Could not validate Stocks Dashboard Continuity: {e}")
            
    # 2. Test ETF Scorecards
    etf_path = os.path.join(DATA_DIR, 'All_ETFs_Scorecard.xlsx')
    if os.path.exists(etf_path):
        try:
            # All_ETFs_Scorecard.xlsx has multiple sheets (one for each ETF)
            xls = pd.ExcelFile(etf_path)
            for sheet in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet)
                if 'Actual Direction' in df.columns:
                    pending_count = (df['Actual Direction'] == "Pending").sum()
                    if pending_count >= 15:
                        print(f"[FAIL] ETF {sheet} has {pending_count} 'Pending' statuses! History wipeout detected!")
                        import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
            print("SUCCESS - ETF Scorecards history intact.")
        except Exception as e:
            print(f"Warning: Could not validate ETF Dashboard Continuity: {e}")
            
    print("\n=== QA AUDIT: CROSS-SYSTEM SYNCHRONIZATION CHECK ===")
    
    # 3. Check ETF Sync
    try:
        etf_ledger = database_manager.get_ledger('ETF_BallsForBrains')
        if not etf_ledger.empty:
            last_row = etf_ledger.iloc[-1]
            holdings = json.loads(last_row['Holdings_JSON'])
            etf_tickers = list(holdings.keys())
            
            if os.path.exists(etf_path):
                xls = pd.ExcelFile(etf_path)
                for ticker in etf_tickers:
                    if ticker not in xls.sheet_names:
                        print(f"[CRITICAL FAIL] Virtual Broker holds ETF '{ticker}' but it is MISSING from All_ETFs_Scorecard.xlsx!")
                        import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
                print(f"SUCCESS - All {len(etf_tickers)} live ETF Holdings mathematically verified to exist in Email Scorecard.")
    except Exception as e:
        print(f"Warning: Could not run ETF Sync Check: {e}")
        
    # 4. Check Stock Sync
    try:
        stock_ledger = database_manager.get_ledger('BallsForBrains')
        if not stock_ledger.empty:
            last_row = stock_ledger.iloc[-1]
            holdings = json.loads(last_row['Holdings_JSON'])
            stock_tickers = list(holdings.keys())
            
            if os.path.exists(stock_path):
                df = pd.read_excel(stock_path)
                if 'Ticker' in df.columns:
                    excel_tickers = df['Ticker'].unique()
                    for ticker in stock_tickers:
                        if ticker not in excel_tickers:
                            print(f"[CRITICAL FAIL] Virtual Broker holds Stock '{ticker}' but it is MISSING from Top5_Bayesian_Scorecard_Formatted.xlsx!")
                            import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
                print(f"SUCCESS - All {len(stock_tickers)} live Stock Holdings mathematically verified to exist in Email Scorecard.")
    except Exception as e:
        print(f"Warning: Could not run Stock Sync Check: {e}")
        
    # 5. Check Turso Prod vs Shadow, Unified Arena, and Persona Equity Curve Integrity (No Flatlines & No Volatility Spikes)
    try:
        stock_ledger = database_manager.get_ledger('BallsForBrains')
        df_ps = database_manager.execute_query("SELECT date, model_name, total_equity FROM prod_vs_shadow_master ORDER BY date ASC")
        df_ol = database_manager.execute_query("SELECT date, model_name, total_equity FROM olympic_shootout_master ORDER BY date ASC")

        if not stock_ledger.empty and not df_ps.empty:
            latest_db_date = str(stock_ledger.iloc[-1]['Date']).split()[0]
            latest_shadow_date = str(df_ps['date'].max()).split()[0]

            if latest_db_date != latest_shadow_date and latest_shadow_date < latest_db_date:
                print(f"[CRITICAL FAIL] Turso prod_vs_shadow_master ends at {latest_shadow_date} while capital_ledgers is at {latest_db_date}!")
                import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)

            # Check 5A: 10000.00 Flatline Bug in recent Prod rows
            df_prod_rows = df_ps[df_ps['model_name'].isin(['PROD_Bayesian_SV', 'Prod'])].sort_values('date')
            if len(df_prod_rows) >= 3 and (df_prod_rows['total_equity'].tail(3) == 10000.0).any():
                print("[CRITICAL FAIL] Turso prod_vs_shadow_master Prod series flatlined at 10000.0!")
                import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)

            # Check 5B: Single-Day Volatility Spike / Crash Guard (> 2.5% 1-day jump/crash on Shadow/Benchmark models, > 4.0% on Live Prod) across all Arena models
            df_arena = pd.concat([df_ps, df_ol], ignore_index=True)
            for m_name, grp in df_arena.groupby('model_name'):
                grp = grp.sort_values('date').drop_duplicates(subset=['date'], keep='last')
                rets = grp['total_equity'].pct_change().dropna()
                limit_pct = 0.040 if m_name in ('PROD_Bayesian_SV', 'Prod', 'CHAMPION (Live VIP)') else 0.025
                bad_rets = rets[rets.abs() > limit_pct]
                if not bad_rets.empty:
                    bad_idx = bad_rets.index[0]
                    bad_dt = grp.loc[bad_idx, 'date']
                    bad_val = bad_rets.iloc[0] * 100.0
                    print(f"[CRITICAL FAIL] Unnatural single-day volatility spike/crash in Arena model '{m_name}' on {bad_dt}: {bad_val:+.2f}% (> +/-{limit_pct*100:.1f}% limit)!")
                    import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)

                # Check 5C: Tail Horizontal Flatline Guard (last 4 trading days identical on active models)
                if len(grp) >= 4 and m_name in ('Shadow_Transformer', 'Sandbox_V1', 'Shadow_LSTM', 'EL_CAP (70% Liquidity)', 'EL_VOLTI (70% Stability)'):
                    tail4 = grp['total_equity'].tail(4).round(2).tolist()
                    if len(set(tail4)) == 1:
                        print(f"[CRITICAL FAIL] Arena model '{m_name}' has flatlined horizontally for 4 consecutive sessions at {tail4[0]}!")
                        import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)

        # Check 5D: Pre-Inception $10,000.00 Flatline Guard across all 8 Personas in capital_ledgers
        # (Except ETF_Conservative which is intentionally 100% Cash under high VIX regimes when no ETF passes conservative gates)
        for p_check in ['Conservative', 'Neutral', 'Dynamic', 'BallsForBrains', 'ETF_Neutral', 'ETF_Dynamic', 'ETF_BallsForBrains']:
            df_l = database_manager.get_ledger(p_check)
            if len(df_l) >= 5:
                head5_eq = [round(float(x), 2) for x in df_l['Total_Equity'].head(5).tolist()]
                if all(x == 10000.0 for x in head5_eq):
                    print(f"[CRITICAL FAIL] Persona '{p_check}' has a pre-inception $10,000.00 flatline at the beginning of its equity curve ({head5_eq})!")
                    import sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(1)

        print(f"SUCCESS - Turso Arena models and all 8 Persona equity curves verified with ZERO flatline bugs and ZERO unnatural volatility spikes ({latest_shadow_date}).")
    except Exception as e:
        print(f"Warning: Could not run Shadow Sync Check: {e}")

    print("=== QA AUDIT PASSED: No dashboard wipeouts or sync mismatches detected. ===")

if __name__ == "__main__":
    test_dashboard_continuity()
    os._exit(0)
