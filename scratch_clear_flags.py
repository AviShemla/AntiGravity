import sqlite3
conn = sqlite3.connect('antigravity.db')
c = conn.cursor()
c.execute("DELETE FROM process_continuity WHERE last_completed_date = '2026-06-12'")
conn.commit()
conn.close()
print("Cleared flags!")
