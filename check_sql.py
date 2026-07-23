import database_manager
df = database_manager.execute_query("SELECT persona, date, intraday_status FROM capital_ledgers WHERE date = '2026-07-23'")
print(df)
