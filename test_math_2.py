import database_manager
conn = database_manager.get_connection()
res = conn._client.execute("SELECT date, total_equity, daily_pnl_json FROM capital_ledgers WHERE persona='Conservative' ORDER BY date ASC LIMIT 5")
for row in res.rows:
    print(row)
