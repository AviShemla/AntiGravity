import os
import datetime
import sys

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
LOG_FILE = os.path.join(BASE_DIR, "master_watchdog.log")

def log_alert(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] QA_TASK_AUDITOR_ALERT: {msg}"
    print(log_line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_line + "\n")
    except Exception:
        pass
        
    try:
        import subprocess
        script_path = os.path.join(r"C:\Users\AviShemla\AntiGravity", "send_email_notification.py")
        subprocess.Popen([r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe", script_path, "AntiGravity QA Alert - Task Auditor", msg], creationflags=0x08000000)
    except Exception as e:
        print(f"Failed to trigger email alert: {e}")

def check_file_freshness(filepath, max_age_hours, task_name):
    if not os.path.exists(filepath):
        log_alert(f"Failed! Missing file for {task_name}: {filepath}")
        return False
        
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
    age_hours = (datetime.datetime.now() - mtime).total_seconds() / 3600
    
    if age_hours > max_age_hours:
        log_alert(f"Failed! {task_name} is STALE. Last run was {age_hours:.1f} hours ago. Expected within {max_age_hours} hours.")
        return False
        
    return True

if __name__ == "__main__":
    print("--- Starting Task Auditor Agent ---")
    errors = 0
    
    # 1. Daily Pipeline (Stock Scorecard) - Max 72 hours to account for weekends/holidays
    file1 = os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx")
    if not check_file_freshness(file1, 72, "Daily Pipeline (Stock Scorecard)"):
        errors += 1
        
    # 2. Weekend Trainer (Stock) - Max 8 days (192 hours)
    file2 = os.path.join(BASE_DIR, "models", "transformer_weights.pt")
    if not check_file_freshness(file2, 192, "Weekend Trainer (Stock)"):
        errors += 1
        
    # 3. Weekend Trainer (ETF) - Max 8 days (192 hours)
    file3 = os.path.join(BASE_DIR, "models", "transformer_etf_weights.pt")
    if not check_file_freshness(file3, 192, "Weekend Trainer (ETF)"):
        errors += 1
        
    # 4. Weekend Fundamentals Scan - Max 8 days (192 hours)
    file4 = os.path.join(BASE_DIR, "financial_data", "SP500_Fundamentals_Score.csv")
    if not check_file_freshness(file4, 192, "Weekend Fundamentals Scan"):
        errors += 1
        
    # 5. MONDAY SYSTEMIC INTEGRITY: Ensure all 8 Personas generated a pending order (even if empty)
    try:
        sys.path.insert(0, BASE_DIR)
        import database_manager
        df_pending = database_manager.execute_query('SELECT persona FROM pending_orders')
        expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                             'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
        found_personas = df_pending['persona'].tolist() if not df_pending.empty else []
        missing = [p for p in expected_personas if p not in found_personas]
        if missing:
            log_alert(f"Failed! Missing Pending Orders for Personas: {missing}. A virtual broker script silently failed or skipped them!")
            errors += 1
    except Exception as e:
        log_alert(f"Failed to query database for Persona Integrity: {e}")
        errors += 1
        
    if errors == 0:
        print("--- All Tasks Audited: PASSED (0 Errors) ---")
    else:
        print(f"--- Task Auditor Failed with {errors} Errors! Alerts sent to watchdog log. ---")
        sys.exit(1)
