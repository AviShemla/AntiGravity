import database_manager as dbm
df = dbm.execute_query("SELECT persona, date, cash, total_equity FROM capital_ledgers WHERE persona LIKE 'ETF_%' AND date='2026-07-23'")
print(df.to_string())
