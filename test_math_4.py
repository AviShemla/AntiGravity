import database_manager
conn = database_manager.get_connection()
res = conn._client.execute("SELECT date, cash, total_equity, holdings_json, daily_pnl_json FROM capital_ledgers WHERE persona='Conservative' AND date='2026-07-09'")
row = res.rows[0]
print("Date:", row[0])
print("Cash:", row[1])
print("Total Equity:", row[2])
print("Holdings:", row[3])
print("PnL:", row[4])
