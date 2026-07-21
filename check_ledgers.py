import os, sys, traceback
import pandas as pd
sys.path.append("/opt/antigravity")
from database_manager import execute_query

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 2000)

try:
    print("--- LATEST CAPITAL LEDGER DATES ---")
    df0 = execute_query("SELECT persona, MAX(date) as latest_date FROM capital_ledgers GROUP BY persona")
    print(df0.to_string())
except Exception as e:
    print("Err0:", e)
os._exit(0)
