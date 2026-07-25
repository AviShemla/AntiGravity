import database_manager as dbm

df = dbm.execute_query("SELECT date, cash, total_equity, holdings_json FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 3")
print(df.to_string())
