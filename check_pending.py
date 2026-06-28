import sqlite3
import json
conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
c = conn.cursor()
c.execute("SELECT * FROM pending_orders WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 2")
for row in c.fetchall(): print(row)
conn.close()
