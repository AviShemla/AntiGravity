from database_manager import execute_query
print("=== PENDING ORDERS ===")
df_pending = execute_query("SELECT persona, ticker, action, quantity, target_price FROM pending_orders")
if df_pending.empty: print("No Pending Orders")
else: print(df_pending.to_string())

print("\n=== INTRADAY ===")
try:
    df_ledger = execute_query("SELECT persona, date, total_equity, cash_balance FROM capital_ledgers ORDER BY date DESC LIMIT 8")
    print(df_ledger.to_string())
except: pass
