import database_manager
print(database_manager.execute_query("SELECT persona, MAX(date) FROM capital_ledgers GROUP BY persona"))
