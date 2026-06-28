import sqlite3
conn=sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
c=conn.cursor()
print('ETF Orders:', c.execute('SELECT COUNT(*) FROM pending_orders WHERE is_etf=1').fetchone()[0])
print('Stock Orders:', c.execute('SELECT COUNT(*) FROM pending_orders WHERE is_etf=0').fetchone()[0])
conn.close()
