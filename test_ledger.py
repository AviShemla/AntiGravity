import os
import sqlite3
import pandas as pd

conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Capital_Ledger.db'))
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", tables)

for p in ['BallsForBrains', 'Conservative']:
    if (p,) in tables:
        df = pd.read_sql(f"SELECT * FROM {p} ORDER BY Date ASC", conn)
        print(f"\n--- {p} Last 5 days ---")
        print(df[['Date', 'Equity', 'Cash', 'Holdings_JSON']].tail(5))
