import database_manager
conn = database_manager.get_connection()
res = conn._client.execute("SELECT date, holdings_json FROM capital_ledgers WHERE persona='Neutral' ORDER BY date DESC LIMIT 2")
for r in res.rows:
    print(r)
