import subprocess
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe"

# Dates that were skipped for Single Stock personas due to missing PyMC scorecards
skipped_dates = [
    "2026-06-10",
    "2026-06-11",
    "2026-06-12",
    "2026-06-15",
    "2026-06-16"
]

print("--- STARTING SINGLE STOCK PATCH SCRIPT ---")
for d in skipped_dates:
    print(f"\n>> Patching Single Stocks for Date: {d} <<")
    subprocess.run([PYTHON_EXE, "virtual_broker.py", "SINGLE", d], cwd=BASE_DIR)
    
    # We do NOT run etf_virtual_broker because ETFs are already at 2026-06-16
    # We MUST run intraday_tracker to commit the single stock trades
    print(f">> Committing Stock Trades via Intraday Tracker for Date: {d} <<")
    subprocess.run([PYTHON_EXE, "intraday_tracker.py", "--target-date", d], cwd=BASE_DIR)

print("\n--- PATCH COMPLETE ---")
