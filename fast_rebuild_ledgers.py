import pandas as pd
import sqlite3
import subprocess
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def reset_db():
    conn = sqlite3.connect(os.path.join(BASE_DIR, "antigravity.db"))
    conn.execute("DELETE FROM capital_ledgers")
    conn.execute("DELETE FROM pending_orders")
    conn.execute("DELETE FROM executed_trades")
    conn.commit()
    conn.close()
    print("Database ledgers wiped clean.")

def get_dates_from_excel(path, skip=2):
    xls = pd.ExcelFile(path)
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], skiprows=skip)
    date_col = 'date' if 'date' in df.columns else 'Date'
    return pd.to_datetime(df[date_col].dropna()).dt.strftime('%Y-%m-%d').tolist()

print("Rebuilding Single Stock Virtual Broker Ledgers...")
reset_db()

stock_dates = get_dates_from_excel(os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx"))
for d in stock_dates:
    print(f"Running virtual_broker for {d}")
    subprocess.run([sys.executable, "virtual_broker.py", "--target-date", d], cwd=BASE_DIR)
    subprocess.run([sys.executable, "intraday_tracker.py", "--target-date", d], cwd=BASE_DIR)

print("\nRebuilding ETF Virtual Broker Ledgers...")
etf_dates = get_dates_from_excel(os.path.join(BASE_DIR, "financial_data", "All_ETFs_Scorecard.xlsx"))
for d in etf_dates:
    print(f"Running etf_virtual_broker for {d}")
    subprocess.run([sys.executable, "etf_virtual_broker.py", "--target-date", d], cwd=BASE_DIR)
    subprocess.run([sys.executable, "intraday_tracker.py", "--target-date", d], cwd=BASE_DIR)

print("\nExporting fresh Dashboards...")
subprocess.run([sys.executable, "export_broker_excel_report.py"], cwd=BASE_DIR)
subprocess.run([sys.executable, "export_etf_broker_excel.py"], cwd=BASE_DIR)
print("\nFAST REBUILD COMPLETE!")
