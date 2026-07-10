import sys
sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
import database_manager
conn = database_manager.get_connection()
res = conn.execute("SELECT date FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 5").fetchall()
for r in res:
    print(r)
