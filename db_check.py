import sqlite3
import pandas as pd

conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
tables = [t[0] for t in conn.cursor().execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"Tables: {tables}")

print('\nLEDGER')
print(pd.read_sql('SELECT persona, MAX(date), total_equity FROM capital_ledgers GROUP BY persona', conn))

print('\nPENDING ORDERS')
print(pd.read_sql('SELECT * FROM pending_orders', conn))

conn.close()
