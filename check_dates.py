import sqlite3
import pandas as pd
conn = sqlite3.connect('antigravity.db')
print("--- BallsForBrains ---")
print(pd.read_sql("SELECT date, total_equity FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 10", conn))
print("\n--- Conservative ---")
print(pd.read_sql("SELECT date, total_equity FROM capital_ledgers WHERE persona='Conservative' ORDER BY date DESC LIMIT 10", conn))
