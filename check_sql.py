import sqlite3
import pandas as pd

conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
df = pd.read_sql("SELECT * FROM capital_ledgers WHERE persona='BallsForBrains' LIMIT 10", conn)
print(df.to_string())
