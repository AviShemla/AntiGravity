import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from database_manager import execute_query

tables = execute_query("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", tables.to_string())

print("\n=== STOCKS ===")
df_stocks = execute_query("SELECT Persona, Intraday_Status, Holdings_JSON, Daily_PnL_JSON FROM capital_ledgers WHERE Date = '2026-07-16'")
print(df_stocks.to_string())
