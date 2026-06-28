import sqlite3
import json
conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
c = conn.cursor()
c.execute("SELECT date, persona, cash, total_equity, holdings_json FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 2")
for row in c.fetchall(): print(row)
conn.close()
