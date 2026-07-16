import database_manager
df = database_manager.execute_query("SELECT date, persona, total_equity FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 5")
print(df)
