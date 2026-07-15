import os
import datetime
import sys
import subprocess
import pandas as pd
import pandas_market_calendars as mcal

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

def check_file_freshness_dynamic(filepath, last_market_close_ts, task_name):
    if not os.path.exists(filepath):
        log_alert(f"Failed! Missing file for {task_name}: {filepath}")
        return False
        
    mtime_ts = pd.Timestamp(os.path.getmtime(filepath), unit='s', tz='UTC').tz_convert('America/New_York')
    
    if mtime_ts < last_market_close_ts:
        log_alert(f"[SELF-HEALING] {task_name} is STALE. Last modified {mtime_ts.strftime('%Y-%m-%d %H:%M')}, but last market close was {last_market_close_ts.tz_convert('America/New_York').strftime('%Y-%m-%d %H:%M')}.")
        return False
        
    return True

def get_expected_market_dates():
    nyse = mcal.get_calendar('NYSE')
    end_date = pd.Timestamp.now(tz='America/New_York')
    start_date = end_date - pd.Timedelta(days=10)
    schedule = nyse.schedule(start_date=start_date, end_date=end_date)
    
    if schedule.empty:
        return None, None, None
        
    today_schedule = schedule[schedule.index.date == end_date.date()]
    if not today_schedule.empty:
        market_close = today_schedule.iloc[0]['market_close']
        if end_date >= market_close:
            last_completed_market_day = end_date.strftime('%Y-%m-%d')
            next_market_day = nyse.schedule(start_date=end_date + pd.Timedelta(days=1), end_date=end_date + pd.Timedelta(days=10)).index[0].strftime('%Y-%m-%d')
            last_market_close_ts = market_close
        else:
            last_completed_market_day = schedule.index[-2].strftime('%Y-%m-%d') if len(schedule) >= 2 else schedule.index[-1].strftime('%Y-%m-%d')
            next_market_day = end_date.strftime('%Y-%m-%d')
            last_market_close_ts = schedule.iloc[-2]['market_close'] if len(schedule) >= 2 else schedule.iloc[-1]['market_close']
    else:
        last_completed_market_day = schedule.index[-1].strftime('%Y-%m-%d')
        next_market_day = nyse.schedule(start_date=end_date + pd.Timedelta(days=1), end_date=end_date + pd.Timedelta(days=10)).index[0].strftime('%Y-%m-%d')
        last_market_close_ts = schedule.iloc[-1]['market_close']
        
    return last_completed_market_day, next_market_day, last_market_close_ts

if __name__ == "__main__":
    print("--- Starting Task Auditor Agent ---")
    errors = 0
    
    last_completed_market_day, next_market_day, last_market_close_ts = get_expected_market_dates()
    
    if last_market_close_ts:
        # 1. Daily Pipeline (Stock Scorecard) - Dynamic Freshness
        file1 = os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx")
        if not check_file_freshness_dynamic(file1, last_market_close_ts, "Daily Pipeline (Stock Scorecard)"):
            errors += 1
            
        # 1.5. Dashboard Check: Prod vs Shadow 
        file_prod = os.path.join(BASE_DIR, "financial_data", "Prod_vs_Shadow_Results_MASTER.csv")
        if not check_file_freshness_dynamic(file_prod, last_market_close_ts, "Prod vs Shadow Dashboard CSV"):
            errors += 1
            log_alert("-> Auto-spawning prod_vs_shadow_tracker.py...")
            subprocess.Popen([r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe", "prod_vs_shadow_tracker.py"], cwd=BASE_DIR, creationflags=0x08000000)
            
        # 1.6. Dashboard Check: Population PnL Race
        file_olympic = os.path.join(BASE_DIR, "financial_data", "Olympic_Shootout_Results_MASTER.csv")
        lock_olympic = os.path.join(BASE_DIR, "run_backtests.lock")
        
        is_backtester_running = False
        import psutil
        for p in psutil.process_iter(['name', 'cmdline']):
            try:
                cmd = " ".join(p.info.get('cmdline', []) or [])
                if 'run_backtests.py' in cmd and 'python' in cmd.lower():
                    is_backtester_running = True
                    break
            except Exception:
                pass
                
        if os.path.exists(lock_olympic) and not is_backtester_running:
            log_alert("[SELF-HEALING] Ghost Lockfile detected for run_backtests.py! Process crashed/killed. Deleting lockfile...")
            os.remove(lock_olympic)
            
        if not is_backtester_running:
            if not check_file_freshness_dynamic(file_olympic, last_market_close_ts, "Population PnL Race Dashboard CSV"):
                errors += 1
                log_alert("-> Auto-spawning run_backtests.py...")
                subprocess.Popen([r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe", "run_backtests.py"], cwd=BASE_DIR, creationflags=0x08000000)
            
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
        
    # 5. SELF-HEALING SYSTEMIC INTEGRITY
    try:
        sys.path.insert(0, BASE_DIR)
        import database_manager
        
        python_exe = r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe"
        
        if last_completed_market_day and next_market_day:
            # Check Ledger Continuity
            df_ledger = database_manager.execute_query('SELECT MAX(date) as max_date FROM capital_ledgers')
            max_ledger_date = df_ledger.iloc[0]['max_date'] if not df_ledger.empty else None
            
            if max_ledger_date is None or max_ledger_date < last_completed_market_day:
                log_alert(f"[SELF-HEALING] Dashboard Data Gap Detected! Ledger max date ({max_ledger_date}) is older than last completed market day ({last_completed_market_day}).")
                log_alert(f"-> Auto-spawning Intraday Tracker to force EOD write for {last_completed_market_day}...")
                subprocess.Popen([python_exe, "intraday_tracker.py", "--target-date", last_completed_market_day], cwd=BASE_DIR, creationflags=0x08000000)
                errors += 1
                
            # Check Pending Orders Continuity (Only between 03:00 AM and 15:55 PM)
            now_ny = pd.Timestamp.now(tz='America/New_York')
            missing = []
            stale = False
            
            if 3 <= now_ny.hour < 15 or (now_ny.hour == 15 and now_ny.minute < 55):
                df_pending = database_manager.execute_query('SELECT persona, date FROM pending_orders')
                expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                                     'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
                found_personas = df_pending['persona'].tolist() if not df_pending.empty else []
                missing = [p for p in expected_personas if p not in found_personas]
                
                if not df_pending.empty:
                    max_pending_date = df_pending['date'].max()
                    if max_pending_date < next_market_day:
                        stale = True
                        log_alert(f"[SELF-HEALING] Stale Pending Orders Detected! Pending date ({max_pending_date}) is older than expected prediction date ({next_market_day}).")
                    
            if missing or stale:
                if missing:
                    log_alert(f"[SELF-HEALING] Missing Pending Orders for Personas: {missing}.")
                
                # Check if catchup is already running to prevent duplicate looping
                import psutil
                is_running = False
                for p in psutil.process_iter(['name', 'cmdline']):
                    try:
                        cmd = " ".join(p.info.get('cmdline', []) or [])
                        if 'laptop_catchup_controller.py' in cmd:
                            is_running = True
                            break
                    except Exception:
                        pass
                
                if is_running:
                    log_alert("-> Pipeline is actively running. Skipping auto-spawn to prevent collisions.")
                else:
                    log_alert("-> Auto-spawning Catch-Up Controller to regenerate scorecards and orders...")
                    subprocess.Popen([python_exe, "laptop_catchup_controller.py"], cwd=BASE_DIR, creationflags=0x08000000)
                    errors += 1
                
    except Exception as e:
        log_alert(f"Failed to query database for Self-Healing Integrity: {e}")
        errors += 1
        
    if errors == 0:
        print("--- All Tasks Audited: PASSED (0 Errors) ---")
    else:
        print(f"--- Task Auditor Failed with {errors} Errors! Self-Healing agents have been dispatched. ---")
        sys.exit(1)
