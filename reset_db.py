import sqlite3
conn = sqlite3.connect('antigravity.db')
conn.execute("UPDATE process_continuity SET last_completed_date='2026-06-02' WHERE pipeline_name='master_pipeline'")
conn.commit()
print("Reset master_pipeline continuity to 2026-06-02")
