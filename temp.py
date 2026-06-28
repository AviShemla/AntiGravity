import sqlite3
import subprocess

conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
conn.execute("UPDATE process_continuity SET last_completed_date='2026-06-14' WHERE pipeline_name='master_pipeline'")
conn.execute("UPDATE process_continuity SET last_completed_date='2026-06-11' WHERE pipeline_name='etf_pipeline'")
conn.commit()
conn.close()

subprocess.run(["C:/Users/AviShemla/AppData/Local/Python/pythoncore-3.14-64/python.exe", "laptop_catchup_controller.py"], cwd="C:/Users/AviShemla/AntiGravity")
