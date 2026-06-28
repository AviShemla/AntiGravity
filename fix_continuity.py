import sqlite3
conn = sqlite3.connect('antigravity.db')
conn.execute("INSERT INTO process_continuity (pipeline_name, last_completed_date) VALUES ('master_pipeline', '2026-06-08') ON CONFLICT(pipeline_name) DO UPDATE SET last_completed_date=excluded.last_completed_date")
conn.execute("INSERT INTO process_continuity (pipeline_name, last_completed_date) VALUES ('etf_pipeline', '2026-06-22') ON CONFLICT(pipeline_name) DO UPDATE SET last_completed_date=excluded.last_completed_date")
conn.commit()
print(conn.execute('SELECT * FROM process_continuity').fetchall())
conn.close()
