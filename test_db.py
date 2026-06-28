import sqlite3
import pandas as pd
conn = sqlite3.connect('antigravity.db')
print(pd.read_sql("SELECT * FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 5", conn))
print("\n--- Process Continuity ---")
print(pd.read_sql("SELECT * FROM process_continuity", conn))
