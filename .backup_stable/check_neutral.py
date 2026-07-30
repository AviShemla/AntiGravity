import database_manager as dbm
df = dbm.execute_query("SELECT date, cash, total_equity FROM capital_ledgers WHERE persona='ETF_Neutral' AND date IN ('2026-07-22', '2026-07-23') ORDER BY date ASC")
print(df.to_string())
