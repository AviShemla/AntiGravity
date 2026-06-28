import sqlite3
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

db1 = sqlite3.connect('antigravity_OLD_CONSERVATIVE_RULES.db')
db2 = sqlite3.connect('antigravity.db')

try:
    df1 = pd.read_sql_query("SELECT * FROM capital_ledgers", db1)
    df2 = pd.read_sql_query("SELECT * FROM capital_ledgers", db2)
    
    latest_df1 = df1.loc[df1.groupby('persona')['id'].idxmax()]
    latest_df2 = df2.loc[df2.groupby('persona')['id'].idxmax()]
    
    print("\n=== MORNING BACKUP ===")
    print(latest_df1[['persona', 'total_equity', 'cash', 'date']].to_string(index=False))
    
    print("\n=== CURRENT PROD ===")
    print(latest_df2[['persona', 'total_equity', 'cash', 'date']].to_string(index=False))
    
except Exception as e:
    print(f"Error: {e}")
