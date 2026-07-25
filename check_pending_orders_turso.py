import database_manager as dbm

df = dbm.execute_query("SELECT persona FROM pending_orders")
if not df.empty:
    print(df.to_string())
else:
    print("NO PENDING ORDERS LEFT")
