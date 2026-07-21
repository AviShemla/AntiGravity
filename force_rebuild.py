import os
import sys
import subprocess

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
python_exe = sys.executable

def run_script(script_name):
    print(f"\n--- Running {script_name} ---")
    script_path = os.path.join(BASE_DIR, script_name)
    res = subprocess.run([python_exe, script_path], cwd=BASE_DIR)
    if res.returncode != 0:
        print(f"!!! Error running {script_name}. Aborting.")
        sys.exit(1)
    print(f"--- {script_name} Completed Successfully ---")

if __name__ == "__main__":
    print("=== BEGINNING SURGICAL REBUILD FOR 2026-07-21 ===")
    
    # 1. Force Single Stock Downloader
    run_script("SPY.py")
    run_script("data_loader.py")
    
    # 2. Run Single Stock Virtual Broker
    run_script("virtual_broker_v2.py")  # I should check if it's virtual_broker.py or v2. Let's use virtual_broker.py unless v2 is standard. 
    # Actually laptop_catchup_controller.py uses virtual_broker.py
    
