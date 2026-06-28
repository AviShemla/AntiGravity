import os
import subprocess
import time
import datetime
import sys

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
        
        # 1. Single Stocks
        run_script(SINGLE_STOCK_SCRIPT, "daily_pipeline.py")
        
        # 2. Cooldown
        cooldown_mins = 10
        log_msg(f"Sleeping for {cooldown_mins} minutes to clear RAM and cool CPU...")
        time.sleep(cooldown_mins * 60)
        
        # 3. ETFs
        run_script(ETF_SCRIPT, "etf_daily_pipeline.py")
        
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
            import subprocess
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
        
        # 7. Executive Assistant Brief (Now includes Ghost Results)
        EXECUTIVE_SCRIPT = os.path.join(BASE_DIR, 'executive_brief.py')
        run_script(EXECUTIVE_SCRIPT, "executive_brief.py")
            
        log_msg("=== MASTER PIPELINE COMPLETELY FINISHED ===")
        
    except Exception as fatal_e:
        err_msg = f"!!! UNEXPECTED MASTER PIPELINE CRASH: {fatal_e} !!!"
        log_msg(err_msg)
        pipeline_errors.append(err_msg)
        
    finally:
        # 7. DEAD MAN'S SWITCH ALERT SYSTEM
        if pipeline_errors:
            log_msg("--- TRIGGERING CRASH ALERT EMAIL ---")
            error_body = "The AntiGravity pipeline encountered the following CRITICAL ERRORS during execution:\\n\\n"
            for err in pipeline_errors:
                error_body += f"- {err}\\n"
            error_body += "\\nPlease check the master_pipeline_log.txt on the server immediately."
            
            ALERT_SCRIPT = os.path.join(BASE_DIR, 'send_email_notification.py')
            try:
                subprocess.run([sys.executable, ALERT_SCRIPT, "🚨 PIPELINE CRASH ALERT 🚨", error_body], check=True, cwd=BASE_DIR)
            except Exception as mail_err:
                log_msg(f"FAILED to send crash alert email: {mail_err}")

if __name__ == "__main__":
    main()
