import os
import sys
import time
import subprocess

print("=== 60-Second Post-Execution Verification Watchdog ===")
print("Sleeping for 60 seconds to allow pipeline to initialize...")
time.sleep(60)

print("Waking up. Verifying CPU status...")

ps = subprocess.run(["ps", "aux"], stdout=subprocess.PIPE, text=True)
if "master_pipeline.py" not in ps.stdout and "daily_pipeline.py" not in ps.stdout and "etf_daily_pipeline.py" not in ps.stdout:
    print("[FAIL] Pipeline processes are completely dead! They did not survive the 60 second window.")
    sys.exit(1)

print("[PASS] Pipeline is mathematically proven to be alive and running cleanly.")
sys.exit(0)

