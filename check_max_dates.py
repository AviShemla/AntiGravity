import sqlite3
import pandas as pd
import os

print("=== DATABASE LEDGER MAX DATES ===")
conn = sqlite3.connect('antigravity.db')
single_stock_max = pd.read_sql("SELECT MAX(date) FROM capital_ledgers WHERE persona NOT LIKE 'ETF_%'", conn).iloc[0,0]
etf_max = pd.read_sql("SELECT MAX(date) FROM capital_ledgers WHERE persona LIKE 'ETF_%'", conn).iloc[0,0]
print(f"Single Stocks DB Max Date: {single_stock_max}")
print(f"ETFs DB Max Date: {etf_max}")
conn.close()

print("\n=== FORMATTED EXCEL SCORECARDS (FINANCIAL_DATA) ===")
try:
    df_single = pd.read_excel('financial_data/Top5_Bayesian_Scorecard_Formatted.xlsx', sheet_name='ROKU', skiprows=2)
    print(f"Single Stocks Excel Max Date: {df_single['Date'].max() if 'Date' in df_single.columns else df_single['date'].max()}")
except Exception as e:
    print(f"Single Stocks Excel Error: {e}")

try:
    df_etf = pd.read_excel('financial_data/ETF_Bayesian_Scorecard_Formatted.xlsx', sheet_name='SPY', skiprows=2)
    print(f"ETFs Excel Max Date: {df_etf['Date'].max() if 'Date' in df_etf.columns else df_etf['date'].max()}")
except Exception as e:
    print(f"ETFs Excel Error: {e}")

print("\n=== DASHBOARD REPORTS (30-DAY TRIAL) ===")
try:
    df_trial_single = pd.read_excel('financial_data/MultiPersona_Broker_30Day_Trial.xlsx', sheet_name='Conservative')
    print(f"Single Stocks Dashboard Max Date: {df_trial_single['Date'].max() if 'Date' in df_trial_single.columns else df_trial_single['date'].max()}")
except Exception as e:
    print(f"Single Stocks Dashboard Error: {e}")

try:
    df_trial_etf = pd.read_excel('financial_data/ETF_Broker_30Day_Trial.xlsx', sheet_name='ETF_Conservative')
    print(f"ETFs Dashboard Max Date: {df_trial_etf['Date'].max() if 'Date' in df_trial_etf.columns else df_trial_etf['date'].max()}")
except Exception as e:
    print(f"ETFs Dashboard Error: {e}")
