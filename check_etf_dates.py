import database_manager
print(database_manager.execute_query("SELECT persona, date FROM capital_ledgers WHERE persona LIKE 'ETF_%' ORDER BY date DESC LIMIT 10"))
