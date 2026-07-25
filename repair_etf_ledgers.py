import database_manager as dbm
import json
import pandas as pd

personas = ["ETF_Conservative", "ETF_Neutral", "ETF_Dynamic", "ETF_BallsForBrains"]

for p in personas:
    df = dbm.execute_query(f"SELECT date, cash, total_equity, daily_pnl_json, holdings_json FROM capital_ledgers WHERE persona='{p}' AND date IN ('2026-07-22', '2026-07-23') ORDER BY date ASC")
    print(f"--- {p} ---")
    print(df.to_string())
    print("\n")
