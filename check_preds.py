import database_manager
df = database_manager.execute_query("SELECT persona, date FROM pending_orders WHERE date = '2026-07-16'")
print(df)
