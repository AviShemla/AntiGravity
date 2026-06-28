import os
import json
import subprocess
from datetime import datetime

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
python_exe = r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe"
LOG_FILE = os.path.join(BASE_DIR, "master_pipeline_log.txt")
STATE_FILE = os.path.join(BASE_DIR, "system_health_streak.json")

def evaluate_health():
    if not os.path.exists(LOG_FILE):
        return False, "master_pipeline_log.txt not found."

    with open(LOG_FILE, 'r', encoding='cp1252', errors='ignore') as f:
        log_content = f.read()

    # 1. Ensure pipeline fully completed
    if "=== MASTER PIPELINE COMPLETELY FINISHED ===" not in log_content:
        return False, "Missing 100% completion flag."

    # 2. Safely strip out known harmless PyTensor Overflow warnings
    import re
    clean_log = re.sub(r'Rewrite failure due to: local_subtensor_merge.*?OverflowError: Python integer 279 out of bounds for int8', '', log_content, flags=re.DOTALL)
    clean_log = re.sub(r'Traceback \(most recent call last\):.*?pytensor.*?OverflowError: Python integer 279 out of bounds for int8', '', clean_log, flags=re.DOTALL)

    # Now check for real fatal errors
    lines = clean_log.split('\n')
    for line in lines:
        if "Exception:" in line or "Error:" in line or "Traceback" in line:
            return False, f"Detected fatal exception: {line.strip()}"

    return True, "100% Perfect Run."

def update_streak(force_send=False):
    state = {"streak": 0, "last_run_date": None, "status": "UNKNOWN"}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
        except:
            pass
            
    today_str = datetime.now().strftime('%Y-%m-%d')
    if state.get("last_run_date") == today_str and not force_send:
        print(f"[{today_str}] Monitor already ran today. Current Streak: {state['streak']}/5")
        return

    is_perfect, reason = evaluate_health()
    
    if force_send:
        is_perfect = True # Override for manual dispatch after manual fixes
    
    if is_perfect:
        state["streak"] += 1
        state["status"] = f"SUCCESS - {reason}"
        print(f"[{today_str}] SUCCESS. Streak increased to: {state['streak']}/5")
        
        # --- DISPATCH MORNING EMAILS ONLY ON 100% PERFECT RUN ---
        print("--> Dispatching Clean Morning Dashboards...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "send_master_email.py")], cwd=BASE_DIR)
        subprocess.run([python_exe, os.path.join(BASE_DIR, "send_etf_email.py")], cwd=BASE_DIR)
        
        CHAMP_SCRIPT = os.path.join(BASE_DIR, 'send_championship_email.py')
        if os.path.exists(CHAMP_SCRIPT):
            subprocess.run([python_exe, CHAMP_SCRIPT], cwd=BASE_DIR)
            
    else:
        state["streak"] = 0
        state["status"] = f"FAILED - {reason}"
        print(f"[{today_str}] FAILURE DETECTED: {reason}. Streak reset to 0/5. EMAILS ABORTED.")

    state["last_run_date"] = today_str

    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

if __name__ == "__main__":
    print("--- Running System Health Monitor ---")
    update_streak()
