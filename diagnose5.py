import sqlite3, json

conn = sqlite3.connect('antigravity.db')
cursor = conn.cursor()

# Delete existing pending order
cursor.execute("DELETE FROM pending_orders WHERE persona='Conservative' AND date='2026-04-28'")

target_cash = 9737.82
target_equity = 10005.54
target_holdings = {"AAL": {"dollars": 267.72, "price": 11.64, "units": 23}}
daily_pnl = {"RF": 5.546072385237177}
executed_trades = {}

cursor.execute('''
    INSERT INTO pending_orders (persona, date, target_cash, target_total_equity, target_holdings_json, daily_pnl_json, executed_intraday_trades_json)
    VALUES (?, ?, ?, ?, ?, ?, ?)
''', ("Conservative", "2026-04-28", target_cash, target_equity, json.dumps(target_holdings), json.dumps(daily_pnl), json.dumps(executed_trades)))

conn.commit()
conn.close()

print("Pending order inserted.")
