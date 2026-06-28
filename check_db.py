import sqlite3
conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
c = conn.cursor()
c.execute("SELECT date, persona, cash, total_equity FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 3")
for row in c.fetchall(): print(row)
conn.close()
