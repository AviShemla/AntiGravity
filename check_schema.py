import sqlite3
conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/financial_data/ag_pipeline_fallback.db')
print(conn.execute('PRAGMA table_info(pending_orders)').fetchall())
conn.close()
