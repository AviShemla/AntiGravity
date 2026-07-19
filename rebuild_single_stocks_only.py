import pandas as pd
import sqlite3
import subprocess
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def reset_db_single_stocks_only():
    conn = sqlite3.connect(os.path.join(BASE_DIR, "antigravity.db"))
    conn.execute("DELETE FROM capital_ledgers WHERE persona NOT LIKE 'ETF_%'")
    conn.execute("DELETE FROM pending_orders WHERE persona NOT LIKE 'ETF_%'")
    conn.execute("DELETE FROM executed_trades WHERE persona NOT LIKE 'ETF_%'")
    conn.commit()
    conn.close()
    print("Single Stock database ledgers wiped clean. ETF ledgers preserved.")

def get_dates_from_excel(path, skip=2):
    xls = pd.ExcelFile(path)
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], skiprows=skip)
    date_col = 'date' if 'date' in df.columns else 'Date'
    return pd.to_datetime(df[date_col].dropna()).dt.strftime('%Y-%m-%d').tolist()

print("Rebuilding Single Stock Virtual Broker Ledgers...")
reset_db_single_stocks_only()

stock_dates = get_dates_from_excel(os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx"))
for d in stock_dates:
    print(f"Running virtual_broker for {d}")
    subprocess.run([sys.executable, "virtual_broker.py", "--target-date", d], cwd=BASE_DIR)
    subprocess.run([sys.executable, "intraday_tracker.py", "--target-date", d], cwd=BASE_DIR)

print("\nExporting fresh Dashboards...")
subprocess.run([sys.executable, "export_broker_excel_report.py"], cwd=BASE_DIR)
print("\nSINGLE STOCK REBUILD COMPLETE!")
