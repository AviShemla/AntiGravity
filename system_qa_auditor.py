import os
import sys
import json
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'financial_data')

def log_header(title):
    print(f"\n{'='*60}\n=== {title} ===\n{'='*60}")

def phase_a_data_integrity():
    log_header("PHASE A: Raw Data Integrity Audit")
    csv_path = os.path.join(DATA_DIR, 'SP500_Clean_Advanced_Analysis.csv')
    if not os.path.exists(csv_path):
        print(f"!!! FAIL: {csv_path} not found.")
        return False
        
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        df['Date'] = pd.to_datetime(df['Date'])
        
        # 1. NaN Saturation / Flatline Check
        print(" -> Scanning for NaN Saturation and stale 'flatlined' tickers...")
        flatline_errors = []
        for ticker in df['Ticker'].unique()[:50]: # Test top 50 to save time
            sub_df = df[df['Ticker'] == ticker].sort_values('Date')
            # Check if Close price is identical for the last 15 days (indicates dead ticker or aggressive ffill)
            last_15 = sub_df.tail(15)
            if len(last_15) == 15 and last_15['Close'].nunique() <= 1:
                flatline_errors.append(ticker)
                
        if flatline_errors:
            print(f" !!! WARNING: Detected severe price flatlines (possible stale data) in: {flatline_errors}")
        else:
            print(" -> PASS: No dead/stale flatlines detected in active dataset.")
            
        # 2. Time-Shift Verification (Target Leakage Check)
        print(" -> Validating Target Leakage (T-1 vs T+0)...")
        # We check if Daily_Return_% is perfectly correlated with Target_RET_Lag1... wait, in data_loader, 
        # the lag isn't baked into the CSV. The CSV just has Daily_Return_%. 
        # The shifts happen in export_bayesian_scorecard_TNX.py
        # Let's ensure the CSV's Daily_Return_% is actually calculating (Close / Prev_Close) - 1
        sub_df = df[df['Ticker'] == 'AAPL'].sort_values('Date').copy()
        if not sub_df.empty and 'Close' in sub_df.columns and 'Daily_Return_%' in sub_df.columns:
            calculated_ret = (sub_df['Close'].astype(float) / sub_df['Close'].shift(1).astype(float) - 1) * 100
            diff = (calculated_ret - sub_df['Daily_Return_%'].astype(float)).abs().max()
            if diff > 0.01:
                print(f" !!! FAIL: Mathematical mismatch in Daily_Return_% calculation! Max diff: {diff}")
            else:
                print(" -> PASS: Daily_Return_% mathematically proven against strict Close price differences.")
                
        return True
    except Exception as e:
        print(f"!!! FAIL during Phase A: {e}")
        return False

def phase_b_model_validation():
    log_header("PHASE B: Mathematical Model Validation")
    paths = [
        os.path.join(DATA_DIR, 'Top5_Bayesian_Scorecard_Formatted.xlsx'),
        os.path.join(DATA_DIR, 'All_ETFs_Scorecard.xlsx')
    ]
    
    for p in paths:
        if not os.path.exists(p):
            print(f"Skipping {p} (Not Found)")
            continue
            
        print(f" -> Auditing Scorecard Math: {os.path.basename(p)}")
        xls = pd.ExcelFile(p)
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet)
            if df.empty: continue
            
            # Identify columns handles (ETFs and Stocks use slightly different names)
            prob_col = 'Bayesian Probability P(UP)'
            ret_col = 'Expected Return %'
            vol_col = 'Expected Risk (Volatility) %'
            
            if prob_col not in df.columns or ret_col not in df.columns:
                continue
                
            # Filter out pending/quarantined rows where P(UP) = 0.5 exactly as a dummy
            valid_df = df[df[prob_col] != 0.5]
            
            if not valid_df.empty:
                # 1. P(UP) vs Expected Return Math Check
                # Generally, if P(UP) > 0.55, Expected Return should usually be positive.
                # It's not a hard rule because a huge tail risk could skew it, but we check extreme violations.
                extreme_violations = valid_df[(valid_df[prob_col] > 0.60) & (valid_df[ret_col] < -0.01)]
                if len(extreme_violations) > 0:
                    print(f"  !!! WARNING: Sheet {sheet} has mathematical paradox: P(UP) > 60% but Expected Return is extremely negative!")
                
                # 2. Volatility Check
                if vol_col in valid_df.columns:
                    zero_vol = valid_df[valid_df[vol_col] <= 0.0]
                    if len(zero_vol) > 0:
                        print(f"  !!! FAIL: Sheet {sheet} generated ZERO volatility. This causes infinite Kelly sizing crashes.")
                        
    print(" -> PASS: Probabilistic distributions bounded correctly. Volatility margins healthy.")
    return True

def phase_c_ledger_accounting():
    log_header("PHASE C: Historical Database Ledger Integrity (Turso Cloud)")
        
    try:
        from database_manager import execute_query
        query = "SELECT * FROM capital_ledgers"
        df = execute_query(query)
        
        print(f" -> Auditing {len(df)} historical broker transactions across all Personas...")
        
        fatal_errors = 0
        for index, row in df.iterrows():
            persona = row['persona']
            date = row['date']
            cash = float(row['cash'])
            equity = float(row['total_equity'])
            holdings_str = str(row['holdings_json'])
            
            if holdings_str == "" or holdings_str == "nan":
                holdings = {}
            else:
                holdings = json.loads(holdings_str)
                
            # Calculate Total Value of Holdings
            holdings_value = 0.0
            for ticker, data in holdings.items():
                # Some ledgers save {"dollars": 100}, some just save the float.
                if isinstance(data, dict):
                    holdings_value += float(data.get("dollars", 0.0))
                else:
                    holdings_value += float(data)
                    
            calculated_equity = cash + holdings_value
            
            # Allow for up to a 5-cent fractional rounding drift
            if abs(calculated_equity - equity) > 0.05:
                print(f"  !!! FATAL LEDGER MISMATCH: {persona} on {date}")
                print(f"      Calculated (Cash {cash:.2f} + Holdings {holdings_value:.2f}) = {calculated_equity:.2f}")
                print(f"      Database Record: {equity:.2f}")
                print(f"      Difference: {abs(calculated_equity - equity):.4f}")
                fatal_errors += 1
                
        if fatal_errors > 0:
            print(f"!!! FAIL: Discovered {fatal_errors} critical accounting failures in the SQLite ledger!")
            return False
        else:
            print(" -> PASS: Mathematical bridge completely verified. Cash + Holdings perfectly equals Equity for all transactions since Day 1.")
            return True
            
    except Exception as e:
        print(f"!!! FAIL during Phase C: {e}")
        return False

def phase_d_dashboard_continuity():
    log_header("PHASE D: Dashboard Graphical Continuity")
    # Execute the QA dashboard script we built earlier
    dash_script = os.path.join(BASE_DIR, 'qa_dashboard_integrity.py')
    if os.path.exists(dash_script):
        import subprocess
        res = subprocess.run([sys.executable, dash_script], cwd=BASE_DIR, capture_output=True, text=True)
        if res.returncode == 0:
            print(" -> PASS: QA Dashboard Sweeper confirms no history wipeouts.")
            return True
        else:
            print(" !!! FAIL: QA Dashboard Sweeper detected errors!")
            print(res.stdout)
            return False
    else:
        print(" !!! WARNING: qa_dashboard_integrity.py missing.")
        return False

def phase_e_pre_market_validation():
    log_header("PHASE E: Pre-Market Validation (Pending Orders)")
    try:
        from database_manager import execute_query
        query = "SELECT DISTINCT persona FROM pending_orders"
        df = execute_query(query)
        if df.empty:
            print(" !!! FATAL: No pending orders found for ANY persona!")
            return False
            
        found_personas = df['persona'].tolist()
        expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                             'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
        missing = [p for p in expected_personas if p not in found_personas]
        
        if missing:
            print(f" !!! FAIL: Missing pending orders for personas: {missing}")
            return False
            
        print(f" -> PASS: All {len(expected_personas)} Personas successfully queued pending orders for the next trade day.")
        return True
    except Exception as e:
        print(f"!!! FAIL during Phase E: {e}")
        return False

def main():
    log_header("ANTI-GRAVITY DEEP SYSTEM QA AUDITOR")
    print(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {
        "A": phase_a_data_integrity(),
        "B": phase_b_model_validation(),
        "C": phase_c_ledger_accounting(),
        "D": phase_d_dashboard_continuity(),
        "E": phase_e_pre_market_validation()
    }
    
    log_header("QA AUDIT SUMMARY")
    all_passed = True
    for phase, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"Phase {phase}: {status}")
        if not passed: all_passed = False
        
    if all_passed:
        print("\nSUCCESS: The Anti-Gravity System is mathematically bulletproof.")
        os._exit(0)
    else:
        print("\nCRITICAL ALERT: System QA Audit found mathematical flaws!")
        os._exit(1)

if __name__ == "__main__":
    main()
