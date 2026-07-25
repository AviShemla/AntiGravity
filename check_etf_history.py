import database_manager as dbm

df = dbm.execute_query("SELECT date, cash, total_equity FROM capital_ledgers WHERE persona='ETF_BallsForBrains' ORDER BY date ASC")
print(df.to_string())
