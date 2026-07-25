import database_manager as dbm
import json

df = dbm.execute_query("SELECT holdings_json, daily_pnl_json, intraday_status FROM capital_ledgers WHERE persona='BallsForBrains' AND date='2026-07-23'")
if not df.empty:
    print(df.to_string())
    print("\nHOLDINGS:")
    print(json.dumps(json.loads(df.iloc[0]['holdings_json']), indent=2))
