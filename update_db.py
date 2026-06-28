import sqlite3
conn=sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
c=conn.cursor()
c.execute('UPDATE process_continuity SET last_completed_date=? WHERE pipeline_name=?', ('2026-06-12', 'etf_pipeline'))
conn.commit()
conn.close()
