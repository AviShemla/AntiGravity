import database_manager
print("Deleting premature 2026-07-23 rows from capital_ledgers...")
database_manager.execute_query("DELETE FROM capital_ledgers WHERE date = '2026-07-23'")
print("Done. Checking max date now:")
print(database_manager.execute_query("SELECT persona, MAX(date) FROM capital_ledgers GROUP BY persona"))
