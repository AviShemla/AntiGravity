import database_manager as dbm

df1 = dbm.execute_query("SELECT persona, date FROM pending_orders")
print("PENDING ORDERS DATES:")
if not df1.empty: print(df1.to_string())

df2 = dbm.execute_query("SELECT persona, date, intraday_status FROM capital_ledgers WHERE date >= '2026-07-23'")
print("LEDGERS DATES:")
if not df2.empty: print(df2.to_string())
