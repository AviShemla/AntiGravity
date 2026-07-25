import database_manager as dbm
import json

df = dbm.execute_query("SELECT * FROM capital_ledgers WHERE persona='ETF_BallsForBrains' ORDER BY date DESC LIMIT 1")
if not df.empty:
    print(df.to_string())
    print("\nHoldings JSON:", df.iloc[0]['holdings_json'])
