import sqlite3
conn=sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
c=conn.cursor()
print(c.execute('SELECT COUNT(*) FROM pending_orders WHERE date=?', ('2026-06-16',)).fetchone()[0])
conn.close()
