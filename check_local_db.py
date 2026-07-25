import sqlite3
import pandas as pd
conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/financial_data/ag_pipeline_fallback.db')
print("TABLES:")
print(pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn))
print("\nPENDING ORDERS:")
try:
    print(pd.read_sql_query("SELECT Persona, Date FROM pending_orders", conn))
except Exception as e:
    print(e)
conn.close()
