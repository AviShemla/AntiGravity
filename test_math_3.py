import database_manager
conn = database_manager.get_connection()
res = conn._client.execute("SELECT date FROM capital_ledgers WHERE persona='Conservative' ORDER BY date ASC LIMIT 1")
print(res.rows[0])
