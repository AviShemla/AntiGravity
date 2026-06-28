import sqlite3

conn = sqlite3.connect('antigravity.db')
c = conn.cursor()

c.execute("SELECT persona, date, target_cash, target_total_equity, target_holdings_json FROM pending_orders")
rows = c.fetchall()
for r in rows:
    print(r)

conn.close()
