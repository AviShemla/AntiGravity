import database_manager
df = database_manager.execute_query("SELECT persona, date, action, ticker, quantity, price, total_equity FROM capital_ledgers WHERE date >= '2026-07-30' ORDER BY date DESC, persona")
print(df.to_string())
