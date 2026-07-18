import os
import sys
import psutil

print("==================================================")
print("   AntiGravity AI Pre-Flight Diagnostic Check")
print("==================================================")

try:
    import config
    print(f"[OK] Configuration loaded.")
    print(f"     -> WORKSPACE: {config.WORKSPACE_DIR}")
    print(f"     -> DATA_DIR:  {config.DATA_DIR}")
    print(f"     -> ENGINE:    {config.BAYESIAN_ENGINE}")
except ImportError:
    print("[FAIL] CRITICAL ERROR: config.py could not be loaded!")
    os._exit(1)

# Check Paths
if not os.path.exists(config.DATA_DIR):
    print(f"[FAIL] CRITICAL ERROR: Data directory missing: {config.DATA_DIR}")
    os._exit(1)
else:
    print(f"[OK] Data directory verified.")

# Check for Zombie PyMC processes
zombie_count = 0
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = proc.info.get('cmdline')
        if cmdline and 'python' in proc.info['name'].lower():
            cmd_str = " ".join(cmdline).lower()
            # We no longer kill 'backtest_worker.py' or 'run_backtests.py' 
            # because the Championship Marathon intentionally runs through the night on low priority!
            if ('master_pipeline.py' in cmd_str or 'process_etf.py' in cmd_str) and proc.pid != os.getpid():
                zombie_count += 1
                proc.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

if zombie_count > 0:
    print(f"[WARNING] Terminated {zombie_count} zombie Python background processes.")
else:
    print(f"[OK] No zombie background processes detected.")

print("\n>>> ALL SYSTEMS GREEN. SAFE TO EXECUTE. <<<")
