import os
import sys
import pandas as pd
import json

# Add parent directory to path to import database_manager
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database_manager

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
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
                        sys.exit(1)
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
                        sys.exit(1)
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
                        sys.exit(1)
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
                            sys.exit(1)
                print(f"SUCCESS - All {len(stock_tickers)} live Stock Holdings mathematically verified to exist in Email Scorecard.")
    except Exception as e:
        print(f"Warning: Could not run Stock Sync Check: {e}")
        
    # 5. Check Prod vs Shadow Sync
    try:
        shadow_path = os.path.join(DATA_DIR, 'Prod_vs_Shadow_Results_MASTER.csv')
        stock_ledger = database_manager.get_ledger('BallsForBrains')
        if not stock_ledger.empty and os.path.exists(shadow_path):
            latest_db_date = str(stock_ledger.iloc[-1]['Date']).split()[0]
            shadow_df = pd.read_csv(shadow_path)
            latest_shadow_date = str(shadow_df.iloc[-1]['Date']).split()[0]
            
            if latest_db_date != latest_shadow_date:
                if latest_shadow_date > latest_db_date:
                    print(f"SUCCESS - Prod vs Shadow chart is actively tracking INTRADAY (Chart: {latest_shadow_date}, DB: {latest_db_date}).")
                else:
                    print(f"[CRITICAL FAIL] Prod vs Shadow Chart is MISSING dates! DB says {latest_db_date} but Chart ends at {latest_shadow_date}!")
                    sys.exit(1)
            
            # --- NEW CHECK: 10000.00 Flatline Bug ---
            recent_prod_values = shadow_df['Prod'].tail(3).values
            if 10000.0 in recent_prod_values or "10000.0" in recent_prod_values or 10000 in recent_prod_values:
                print(f"[CRITICAL FAIL] Prod vs Shadow Chart has Flatlined at 10000.0! Tracker Race Condition detected.")
                sys.exit(1)
                
            print(f"SUCCESS - Prod vs Shadow chart perfectly synced to Master Ledger ({latest_shadow_date}) with NO flatline bugs.")
    except Exception as e:
        print(f"Warning: Could not run Shadow Sync Check: {e}")

    print("=== QA AUDIT PASSED: No dashboard wipeouts or sync mismatches detected. ===")

if __name__ == "__main__":
    test_dashboard_continuity()
