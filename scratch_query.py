import database_manager as db
import sys
import os

print("Querying capital_ledgers...")
df = db.execute_query("SELECT * FROM capital_ledgers WHERE persona='BallsForBrains' AND date>='2026-07-30'")
print(df.to_string())

sys.stdout.flush()
os._exit(0)
