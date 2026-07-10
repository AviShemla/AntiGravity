import os
import subprocess
import sys

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"

# We must clear the pending_orders table for BallsForBrains to prevent intraday_tracker from executing old ghost orders or future orders during the rebuild
import database_manager
conn = database_manager.get_connection()._client
conn.execute("DELETE FROM pending_orders WHERE persona IN ('BallsForBrains', 'ETF_BallsForBrains')")
conn.close()

# The missing trading days from genesis (June 25) up to the day before the first surviving row (July 8)
dates = [
    "2026-06-26",
    "2026-06-29",
    "2026-06-30",
    "2026-07-01",
    "2026-07-02",
    "2026-07-06",
    "2026-07-07"
]

for d in dates:
    print(f"\n=======================")
    print(f"REBUILDING DAY: {d}")
    print(f"=======================\n")
    
    # 1. Stage orders
    subprocess.run([sys.executable, "virtual_broker.py", "--target-date", d], cwd=BASE_DIR)
    subprocess.run([sys.executable, "etf_virtual_broker.py", "--target-date", d], cwd=BASE_DIR)
    
    # 2. Execute orders (writes to capital_ledgers)
    subprocess.run([sys.executable, "intraday_tracker.py", "--target-date", d], cwd=BASE_DIR)

print("\nHistory Rebuild Complete!")
