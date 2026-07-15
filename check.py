import database_manager
print(database_manager.execute_query("SELECT * FROM capital_ledgers WHERE persona='Neutral' AND date='2026-07-15'").to_dict('records'))
