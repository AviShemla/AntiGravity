import pandas as pd
import sqlite3
import os
import sys

def test_data_gaps_per_ticker(csv_path):
    print("Running QA: Per-Ticker Data Continuity & Gap Detection...")
    if not os.path.exists(csv_path):
        print(f"FAILED: {csv_path} not found.")
        return False
        
    df = pd.read_csv(csv_path, low_memory=False)
    if df.empty:
        print("FAILED: CSV is empty.")
        return False
        
    df['Date'] = pd.to_datetime(df['Date'])
    global_max_date = df['Date'].max()
    
    max_dates = df.groupby('Ticker')['Date'].max()
    
    failed_tickers = []
    for ticker, t_max in max_dates.items():
        if t_max < global_max_date:
            failed_tickers.append((ticker, t_max.strftime('%Y-%m-%d')))
            
    if failed_tickers:
        print(f"FAILED: Found {len(failed_tickers)} tickers missing recent data (global max is {global_max_date.strftime('%Y-%m-%d')}):")
        for t, d in failed_tickers[:10]:
            print(f"  - {t} stuck on {d}")
        if len(failed_tickers) > 10: print("  - ...")
        return False
        
    print("PASSED: All tickers in the dataset are fully up to date with no gaps at the tail end.")
    return True

def test_orphaned_tickers_in_db(db_path, csv_path):
    print("\nRunning QA: SQLite Ledger Orphaned Holdings Verification...")
    import json
    
    df = pd.read_csv(csv_path, low_memory=False)
    available_tickers = set(df['Ticker'].unique())
    
    from database_manager import execute_query
    try:
        df_ledgers = execute_query("SELECT Persona, Holdings_JSON FROM capital_ledgers WHERE Persona NOT LIKE 'ETF_%'")
    except Exception as e:
        print(f"FAILED: Turso Database error {e}")
        return False
    
    missing = []
    for idx, row in df_ledgers.iterrows():
        try:
            holdings = json.loads(row['Holdings_JSON'])
            for t in holdings.keys():
                if t != 'Cash' and t not in available_tickers:
                    missing.append(t)
        except Exception:
            pass
            
    if missing:
        print(f"FAILED: The following tickers are actively held in the database but completely missing from the master CSV: {set(missing)}")
        return False
        
    print("PASSED: All active holdings in the database are successfully represented in the master dataset.")
    return True

if __name__ == '__main__':
    csv_path = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv'
    db_path = r'C:\Users\AviShemla\AntiGravity\antigravity.db'
    
    pass1 = test_data_gaps_per_ticker(csv_path)
    pass2 = test_orphaned_tickers_in_db(db_path, csv_path)
    
    if pass1 and pass2:
        print("\n[QA COMPLETE] All per-ticker continuity and orphaned holding checks passed.")
        sys.exit(0)
    else:
        print("\n[QA COMPLETE] Critical data continuity failures detected.")
        sys.exit(1)
