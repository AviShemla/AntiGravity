import os
import subprocess
import sys

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
python_exe = sys.executable
target_date = "2026-06-15"

print("\n=== RESUMING PIPELINE ===")

print("\n--> Running virtual_broker.py...")
subprocess.run([python_exe, os.path.join(BASE_DIR, "virtual_broker.py"), "--target-date", target_date], cwd=BASE_DIR, check=True)

print("\n--> Running intraday_tracker.py (EOD execution)...")
subprocess.run([python_exe, os.path.join(BASE_DIR, "intraday_tracker.py"), "--target-date", target_date], cwd=BASE_DIR, check=True)

print("\n--> Running export_broker_excel_report.py...")
subprocess.run([python_exe, os.path.join(BASE_DIR, "export_broker_excel_report.py")], cwd=BASE_DIR)

qa_script = os.path.join(BASE_DIR, "qa_blacklist.py")
if os.path.exists(qa_script):
    print("\n--> Running QA Blacklist Audit...")
    subprocess.run([python_exe, qa_script], cwd=BASE_DIR)

# Write to ledger completed
print("\n--> Marking pipeline as complete in ledger...")
import sqlite3
db_path = os.path.join(BASE_DIR, 'financial_data', 'Capital_Ledger.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("INSERT OR REPLACE INTO completion_ledger (pipeline_name, date) VALUES (?, ?)", ('master_pipeline', target_date))
conn.commit()
conn.close()

print("\n--> Sending Consolidated Email Dashboard...")
subprocess.run([python_exe, os.path.join(BASE_DIR, "executive_brief.py")], cwd=BASE_DIR)

print("\n--> Running ETF Pipeline...")
subprocess.run([python_exe, os.path.join(BASE_DIR, "etf_daily_pipeline.py")], cwd=BASE_DIR)

print("\n=== RESUME COMPLETE ===")
