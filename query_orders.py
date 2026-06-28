import sqlite3
conn=sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
c=conn.cursor()
print(c.execute('SELECT * FROM pending_orders').fetchall())
conn.close()
