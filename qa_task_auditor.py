import os
import sys
import datetime
import subprocess
import pandas as pd
import pandas_market_calendars as mcal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "send_email_notification.py")
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
    
    if schedule.empty: return None, None, None
        
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
    print("--- Starting Task Auditor Agent (10-Point Green Light QA) ---")
    errors = 0
    
    last_completed_market_day, next_market_day, last_market_close_ts = get_expected_market_dates()
    
    # QA 9: Zombie Lockfile & Dead Process Janitor
    print("[QA 9] Running clean_ghosts.py (Zombie Hunter)...")
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "clean_ghosts.py")], cwd=BASE_DIR)

    def validate_csv_freshness(filepath, target_date_str, name="[QA]"):
        if not os.path.exists(filepath):
            log_alert(f"{name} MISSING FILE: {filepath}")
            return False
        try:
            df = pd.read_csv(filepath)
            max_date = df['Date'].max()
            if max_date < target_date_str:
                log_alert(f"{name} STALE DATA DETECTED! Max Date: {max_date} < Target Date: {target_date_str}")
                return False
            return True
        except Exception as e:
            log_alert(f"{name} ERROR reading CSV: {e}")
            return False

    if last_completed_market_day:
        # QA 1: Daily Pipeline (Stock Scorecard)
        file_stock = os.path.join(BASE_DIR, "financial_data", "Top5_Bayesian_Scorecard_Formatted.xlsx")
        if not check_file_freshness_dynamic(file_stock, last_market_close_ts, "[QA 1] Stock Scorecard Pipeline"): errors += 1

        # QA 2: Daily Pipeline (ETF Scorecard)
        file_etf = os.path.join(BASE_DIR, "financial_data", "All_ETFs_Scorecard.xlsx")
        if not check_file_freshness_dynamic(file_etf, last_market_close_ts, "[QA 2] ETF Scorecard Pipeline"): errors += 1

        # Check running processes
        import psutil
        is_tracker_running = any('prod_vs_shadow_tracker.py' in " ".join(p.info.get('cmdline', []) or []) for p in psutil.process_iter(['cmdline']))
        is_backtester_running = any('run_backtests.py' in " ".join(p.info.get('cmdline', []) or []) for p in psutil.process_iter(['cmdline']))

        # Deep validation for Dashboard Trackers (Checking actual max Date inside CSV)
        if not is_tracker_running:
            file_shadow = os.path.join(BASE_DIR, "financial_data", "Prod_vs_Shadow_Results_MASTER.csv")
            if not validate_csv_freshness(file_shadow, last_completed_market_day, "[QA 3] Prod vs Shadow Dashboard CSV"):
                errors += 1
                log_alert(f"-> Auto-spawning prod_vs_shadow_tracker.py for {last_completed_market_day}...")
                subprocess.Popen([sys.executable, "prod_vs_shadow_tracker.py", last_completed_market_day], cwd=BASE_DIR, creationflags=0x08000000)
                
        if not is_backtester_running:
            file_olympic = os.path.join(BASE_DIR, "financial_data", "Olympic_Shootout_Results_MASTER.csv")
            if not validate_csv_freshness(file_olympic, last_completed_market_day, "[QA 3] Population PnL Race Dashboard CSV"):
                errors += 1
                log_alert("-> Auto-spawning run_backtests.py...")
                subprocess.Popen([sys.executable, "run_backtests.py"], cwd=BASE_DIR, creationflags=0x08000000)
            
    # QA 4: Weekend Trainers
    file2 = os.path.join(BASE_DIR, "models", "transformer_weights.pt")
    if not check_file_freshness(file2, 192, "[QA 4] Weekend Trainer (Stock)"): errors += 1
    file3 = os.path.join(BASE_DIR, "models", "transformer_etf_weights.pt")
    if not check_file_freshness(file3, 192, "[QA 4] Weekend Trainer (ETF)"): errors += 1

    # QA 7: Uvicorn Server & Port 80 Deadlock Audit
    import urllib.request
    try:
        if urllib.request.urlopen("http://66.42.118.26/", timeout=5).getcode() != 200:
            log_alert("[QA 7] Remote VPS Uvicorn Deadlock Detected!")
            errors += 1
    except Exception as e:
        log_alert(f"[QA 7] Remote VPS Uvicorn Error: {e}")
        errors += 1

    try:
        sys.path.insert(0, BASE_DIR)
        import database_manager
        
        # QA 8: Zero-Trust Database Schema Interlock
        df_pragma = database_manager.execute_query("PRAGMA table_info(pending_orders);")
        columns = df_pragma['name'].tolist() if not df_pragma.empty else []
        required = ['target_holdings_json', 'executed_intraday_trades_json', 'date', 'persona']
        missing_cols = [c for c in required if c not in columns]
        if missing_cols:
            log_alert(f"[QA 8] Schema Drift Detected! Turso DB pending_orders is missing columns: {missing_cols}")
            errors += 1
            
        if last_completed_market_day and next_market_day:
            # QA 5: DB Continuity & Population (Flatline Check)
            df_ledger = database_manager.execute_query('SELECT MAX(date) as max_date FROM capital_ledgers')
            max_ledger_date = df_ledger.iloc[0]['max_date'] if not df_ledger.empty else None
            
            if max_ledger_date is None or max_ledger_date < last_completed_market_day:
                log_alert(f"[QA 5] Dashboard Data Gap Detected! Ledger max date ({max_ledger_date}) < ({last_completed_market_day}).")
                log_alert(f"-> Auto-spawning Intraday Tracker to force EOD write for {last_completed_market_day}...")
                subprocess.Popen([sys.executable, "intraday_tracker.py", "--target-date", last_completed_market_day], cwd=BASE_DIR, creationflags=0x08000000)
                errors += 1
                
            # QA 6: Market Open Readiness
            df_pending = database_manager.execute_query('SELECT persona, date FROM pending_orders')
            expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                                 'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
            found_personas = df_pending['persona'].tolist() if not df_pending.empty else []
            missing = [p for p in expected_personas if p not in found_personas]
            
            stale = False
            if not df_pending.empty:
                max_pending_date = df_pending['date'].max()
                if max_pending_date < next_market_day:
                    stale = True
                    log_alert(f"[QA 6] Stale Pending Orders Detected! Pending date ({max_pending_date}) < expected ({next_market_day}).")
                
            if missing or stale:
                if missing: log_alert(f"[QA 6] Missing Pending Orders for Personas: {missing}.")
                is_running = any('laptop_catchup_controller.py' in " ".join(p.info.get('cmdline', []) or []) for p in psutil.process_iter(['cmdline']))
                if is_running:
                    log_alert("-> Pipeline is actively running. Skipping auto-spawn.")
                else:
                    log_alert("-> Auto-spawning Catch-Up Controller...")
                    subprocess.Popen([sys.executable, "laptop_catchup_controller.py"], cwd=BASE_DIR, creationflags=0x08000000)
                    errors += 1
                    
        # QA 10: ETF/Stock Sequencing
        stock_last = database_manager.get_last_continuity_date('master_pipeline')
        etf_last = database_manager.get_last_continuity_date('etf_pipeline')
        if etf_last and stock_last and etf_last > stock_last:
            log_alert(f"[QA 10] Interlock Violation: ETF Pipeline ({etf_last}) is ahead of Stock Pipeline ({stock_last}). Stale priors used!")
            errors += 1

    except Exception as e:
        log_alert(f"Failed to query database for QA Checks: {e}")
        errors += 1
        
    if errors == 0:
        print("--- All Tasks Audited: PASSED (10/10 Checks Green) ---")
        sys.stdout.flush()
        os._exit(0)
    else:
        print(f"--- Task Auditor Failed with {errors} Errors! Self-Healing agents have been dispatched. ---")
        sys.stdout.flush()
        os._exit(1)
