import os, sys, traceback
sys.path.append("/opt/antigravity")
from database_manager import execute_query

try:
    print("--- PENDING ORDERS ---")
    df0 = execute_query("SELECT * FROM pending_orders")
    print(df0.to_string())
except Exception as e:
    print("Err0:", e)

try:
    print("--- TRANSACTION LOG ---")
    df = execute_query("SELECT persona, date, ticker, action, quantity, price FROM transaction_log ORDER BY date DESC LIMIT 30")
    print(df.to_string())
except Exception as e:
    print("Err1:", e)
    
try:
    print("--- CAPITAL LEDGERS ---")
    df2 = execute_query("SELECT persona, date, total_equity, cash_balance FROM capital_ledgers ORDER BY date DESC LIMIT 10")
    print(df2.to_string())
except Exception as e:
    print("Err2:", e)
os._exit(0)
