import os
import subprocess
import time
import datetime
import sys
import psutil
import atexit

LOCK_FILE = r"C:\Users\AviShemla\AntiGravity\master_pipeline.lock"
try:
    lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    def release_lock():
        try:
            os.close(lock_fd)
        except:
            pass
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    atexit.register(release_lock)
except FileExistsError:
    print("FATAL: Master Pipeline is already running. OS Lockfile prevents duplicate execution.")
    sys.exit(1)

try:
    # Elevate the master production pipeline to HIGH PRIORITY to ensure live trades never get starved
    psutil.Process(os.getpid()).nice(psutil.HIGH_PRIORITY_CLASS)
except Exception as e:
    pass

# Paths
BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
SINGLE_STOCK_SCRIPT = os.path.join(BASE_DIR, 'daily_pipeline.py')
ETF_SCRIPT = os.path.join(BASE_DIR, 'etf_daily_pipeline.py')
FUNDAMENTALS_SCRIPT = os.path.join(BASE_DIR, 'extract_fundamentals.py')

def log_msg(msg):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}")

pipeline_errors = []

def run_script(script_path, script_name):
    log_msg(f"--- STARTING: {script_name} ---")
    try:
        # Run the script and wait for it to complete
        subprocess.run([sys.executable, script_path], check=True, cwd=BASE_DIR)
        log_msg(f"--- COMPLETED SUCCESSFULLY: {script_name} ---")
    except subprocess.CalledProcessError as e:
        err_msg = f"!!! ERROR: {script_name} failed with exit code {e.returncode} !!!"
        log_msg(err_msg)
        pipeline_errors.append(err_msg)
        # We continue to the next script even if one fails
    except Exception as e:
        err_msg = f"!!! FATAL ERROR: Could not execute {script_name}: {e} !!!"
        log_msg(err_msg)
        pipeline_errors.append(err_msg)

def main():
    try:
        log_msg("=== INITIATING ANTI-GRAVITY MASTER PIPELINE ===")
        # 0.5 Pre-Flight QA Data Integrity Check
        log_msg("--- Initiating Pre-Flight QA Data Integrity Check ---")
        QA_SCRIPT = os.path.join(BASE_DIR, 'qa_data_alignment.py')
        qa_res = subprocess.run([sys.executable, QA_SCRIPT], cwd=BASE_DIR)
        if qa_res.returncode != 0:
            log_msg("!!! FATAL: Pre-Flight QA Check Failed. Aborting Pipeline to prevent array mismatch deadlocks !!!")
            sys.exit(1)
            
        # 1. Single Stocks
        run_script(SINGLE_STOCK_SCRIPT, "daily_pipeline.py")
        
        # 2. Cooldown
        cooldown_mins = 2
        log_msg(f"Sleeping for {cooldown_mins} minutes to clear RAM and cool CPU...")
        time.sleep(cooldown_mins * 60)
        
        # 3. ETFs
        run_script(ETF_SCRIPT, "etf_daily_pipeline.py")
        
        # 3.5 Deep Learning Shadow Inference
        log_msg("--- Initiating Deep Learning Shadow Inference ---")
        DL_INFERENCE_SCRIPT = os.path.join(BASE_DIR, 'daily_dl_inference.py')
        run_script(DL_INFERENCE_SCRIPT, "daily_dl_inference.py")
        
        # 3.8 Generate Daily Excel Reports (Fixing QA Desync)
        log_msg("--- Generating Daily Excel Reports ---")
        run_script(os.path.join(BASE_DIR, 'export_broker_excel_report.py'), "export_broker_excel_report.py")
        run_script(os.path.join(BASE_DIR, 'export_etf_broker_excel.py'), "export_etf_broker_excel.py")
        run_script(os.path.join(BASE_DIR, 'export_bayesian_scorecard_formatted.py'), "export_bayesian_scorecard_formatted.py")
        run_script(os.path.join(BASE_DIR, 'export_etf_scorecard.py'), "export_etf_scorecard.py")

        
        # 4. Weekend Fundamentals Check
        today = datetime.datetime.now()
        if today.weekday() == 5:  # Saturday is 5 in Python's datetime
            log_msg("Saturday detected. Initiating Weekly Fundamentals Extraction.")
            log_msg(f"Sleeping for {cooldown_mins} minutes to clear RAM...")
            time.sleep(cooldown_mins * 60)
            run_script(FUNDAMENTALS_SCRIPT, "extract_fundamentals.py")
        # 5. Git Auto-Backup
        log_msg("--- Initiating Git Auto-Backup ---")
        try:
            subprocess.run(["git", "add", "."], cwd=BASE_DIR, check=True)
            subprocess.run(["git", "commit", "-m", f"Auto-Backup: Pipeline execution on {today.strftime('%Y-%m-%d')}"], cwd=BASE_DIR)
            log_msg("Git Auto-Backup completed successfully.")
        except Exception as e:
            log_msg(f"Git Auto-Backup skipped or failed: {e}")
            
        # 6. A/B Testing: Mega-Macro Ghost Pipeline
        log_msg("--- Extracting Mega-Macro Predictors ---")
        MEGA_MACRO_SCRIPT = os.path.join(BASE_DIR, 'extract_mega_macro.py')
        run_script(MEGA_MACRO_SCRIPT, "extract_mega_macro.py")
        
        log_msg("--- Initiating Ghost Pipeline A/B Test ---")
        TNX_GHOST_SCRIPT = os.path.join(BASE_DIR, 'export_bayesian_scorecard_TNX.py')
        run_script(TNX_GHOST_SCRIPT, "export_bayesian_scorecard_TNX.py")
        
        # 6.5 Dashboard Continuity QA Sweep
        log_msg("--- Running Dashboard Continuity QA Sweep ---")
        DASH_QA_SCRIPT = os.path.join(BASE_DIR, 'qa_dashboard_integrity.py')
        qa_dash_res = subprocess.run([sys.executable, DASH_QA_SCRIPT], cwd=BASE_DIR)
        if qa_dash_res.returncode != 0:
            log_msg("!!! FATAL: Dashboard Continuity QA Check Failed. Sync Mismatch Detected! Aborting Pipeline !!!")
            sys.exit(1)
        
        # 7. Executive Assistant Brief (Now includes Ghost Results)
        EXECUTIVE_SCRIPT = os.path.join(BASE_DIR, 'executive_brief.py')
        run_script(EXECUTIVE_SCRIPT, "executive_brief.py")
            
        # 7.5 FINANCIAL QA AUDIT
        log_msg("--- Running Strict Financial QA Audit ---")
        FINANCIAL_QA_SCRIPT = os.path.join(BASE_DIR, 'qa_financial_audit.py')
        fin_qa_res = subprocess.run([sys.executable, FINANCIAL_QA_SCRIPT], cwd=BASE_DIR)
        if fin_qa_res.returncode != 0:
            log_msg("!!! FATAL: Phantom Bleed or Accounting Error Detected! Aborting Pipeline !!!")
            sys.exit(1)
            
        # 8. Continuous 1-Day Predictive Run
        log_msg("--- Initiating 1-Day Predictive Run ---")
        MARATHON_SCRIPT = os.path.join(BASE_DIR, 'run_backtests.py')
        run_script(MARATHON_SCRIPT, "run_backtests.py")
        
        # 8.5 Send Email Reports
        log_msg("--- Sending Master Email Reports ---")
        MASTER_EMAIL_SCRIPT = os.path.join(BASE_DIR, 'send_master_email.py')
        run_script(MASTER_EMAIL_SCRIPT, "send_master_email.py")
        
        log_msg("--- Sending ETF Email Reports ---")
        ETF_EMAIL_SCRIPT = os.path.join(BASE_DIR, 'send_etf_email.py')
        run_script(ETF_EMAIL_SCRIPT, "send_etf_email.py")

        # --- NEW: SYSTEM HEALTH MONITOR ---
        # Note: We must run this explicitly AFTER the COMPLETELY FINISHED string is logged
        print("--- Updating Prod vs Shadow Tracker ---")
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "prod_vs_shadow_tracker.py")], check=True)
        print("=== PIPELINE COMPLETE ===")
        MONITOR_SCRIPT = os.path.join(BASE_DIR, 'system_health_monitor.py')
        subprocess.run([sys.executable, MONITOR_SCRIPT], cwd=BASE_DIR)
        
    except Exception as fatal_e:
        err_msg = f"!!! UNEXPECTED MASTER PIPELINE CRASH: {fatal_e} !!!"
        log_msg(err_msg)
        pipeline_errors.append(err_msg)

if __name__ == "__main__":
    main()
