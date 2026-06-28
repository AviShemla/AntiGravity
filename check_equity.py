import sqlite3
import pandas as pd
conn = sqlite3.connect('antigravity.db')
query = "SELECT persona, total_equity, cash, date FROM capital_ledgers WHERE persona NOT LIKE 'ETF_%' ORDER BY date DESC LIMIT 8"
print(pd.read_sql(query, conn))
