import pandas as pd
import subprocess
import sys
import os

print("--- STARTING HISTORICAL REPLAY ---")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_PATH = os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx")

PYTHON_EXE = r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe"

try:
    xls = pd.ExcelFile(EXCEL_PATH)
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], skiprows=2)
    
    date_col = 'date' if 'date' in df.columns else 'Date'
    df[date_col] = pd.to_datetime(df[date_col])
    dates = df[date_col].dt.strftime('%Y-%m-%d').tolist()
    
    for d in dates:
        print(f"\n>> Replaying Single Stocks for Date: {d} <<")
        subprocess.run([PYTHON_EXE, "virtual_broker.py", "SINGLE", d], cwd=BASE_DIR)
        
        print(f"\n>> Replaying ETFs for Date: {d} <<")
        subprocess.run([PYTHON_EXE, "etf_virtual_broker.py", "ETF", d], cwd=BASE_DIR)
        
        print(f"\n>> Committing Trades to Ledger via Intraday Tracker for Date: {d} <<")
        subprocess.run([PYTHON_EXE, "intraday_tracker.py", "--target-date", d], cwd=BASE_DIR)
        
    print("\n--- REPLAY COMPLETE. RE-RUNNING MARATHON SHOOTOUT ---")
    subprocess.run([PYTHON_EXE, "run_backtests.py"], cwd=BASE_DIR)
    
    print("\n=== ALL HISTORICAL LEDGERS REBUILT SUCCESSFULLY ===")
    
except Exception as e:
    print(f"Error during replay: {e}")
