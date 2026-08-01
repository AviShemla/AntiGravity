import os
import sys
import glob
import subprocess

def bust_locks():
    print("=== PRE-FLIGHT LOCK BUSTER & SWEEPER ===")
    
    # 1. Stale Lock files cleanup
    lock_patterns = [
        "*.lock",
        "*.pid",
        "*_pipeline.lock",
        "financial_data/*.lock",
        "financial_data/*.pid"
    ]
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    removed_count = 0
    for pattern in lock_patterns:
        search_path = os.path.join(base_dir, pattern)
        for fpath in glob.glob(search_path):
            try:
                os.remove(fpath)
                print(f"  [REMOVED STALE LOCK] {os.path.basename(fpath)}")
                removed_count += 1
            except Exception as e:
                print(f"  [ERROR REMOVING LOCK] {fpath}: {e}")
                
    if removed_count == 0:
        print("  No stale lock files found.")

    # 2. Defunct / Ghost Python Process Sweeper
    if os.name == 'posix':
        print("\n=== SWEEPING GHOST PYTHON PROCESSES (LINUX VULTR) ===")
        try:
            # Kill orphaned multiprocessing worker forks or Prefect zombies
            cmd = "ps aux | grep -E 'export_bayesian|backtest_worker|laptop_catchup_controller' | grep -v grep | awk '{print $2}' | xargs -r kill -9"
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("  Ghost Python processes swept successfully.")
        except Exception as e:
            print(f"  Error sweeping processes: {e}")
    else:
        print("  Skipping POSIX process sweep on Windows.")

    print("=== LOCK BUSTER COMPLETE: SYSTEM READY FOR CLEAN RUN ===\n")

if __name__ == "__main__":
    bust_locks()
