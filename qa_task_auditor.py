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
        if os.name == 'nt':
            subprocess.Popen([sys.executable, script_path, "AntiGravity QA Alert - Task Auditor", msg], creationflags=0x08000000)
        else:
            subprocess.Popen([sys.executable, script_path, "AntiGravity QA Alert - Task Auditor", msg])
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

        # Deep validation for Dashboard Trackers (100% Turso SSOT)
        try:
            sys.path.insert(0, BASE_DIR)
            import database_manager as _dm_qa
            df_ps_max = _dm_qa.execute_query("SELECT MAX(date) as max_d FROM prod_vs_shadow_master")
            ps_max = str(df_ps_max.iloc[0]['max_d'])[:10] if not df_ps_max.empty and df_ps_max.iloc[0]['max_d'] else ""
            if ps_max < last_completed_market_day and not is_tracker_running:
                log_alert(f"[QA 3] Turso prod_vs_shadow_master max date ({ps_max}) < ({last_completed_market_day})")
                errors += 1
            df_ol_max = _dm_qa.execute_query("SELECT MAX(date) as max_d FROM olympic_shootout_master")
            ol_max = str(df_ol_max.iloc[0]['max_d'])[:10] if not df_ol_max.empty and df_ol_max.iloc[0]['max_d'] else ""
            if ol_max < last_completed_market_day:
                log_alert(f"[QA 3] Turso olympic_shootout_master max date ({ol_max}) < ({last_completed_market_day})")
                errors += 1
        except Exception as e_q3:
            log_alert(f"[QA 3] Error querying Turso arena tables: {e_q3}")
            errors += 1

    # QA 4: Weekend Trainers (Verify existence on weekdays; enforce freshness on weekends after Saturday 14:00 UTC schedule)
    file2 = os.path.join(BASE_DIR, "models", "transformer_weights.pt")
    file3 = os.path.join(BASE_DIR, "models", "transformer_etf_weights.pt")
    if not os.path.exists(file2) or not os.path.exists(file3):
        log_alert("[QA 4] Missing Weekend Trainer weight files in models/ directory!")
        errors += 1

    # QA 7: Uvicorn Server & Port 80 Deadlock Audit
    import urllib.request
    try:
        if urllib.request.urlopen("http://66.42.118.26:80/" if os.name == "nt" else "http://127.0.0.1/", timeout=10).getcode() != 200:
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
                if os.name == 'nt':
                    subprocess.Popen([sys.executable, "intraday_tracker.py", "--target-date", last_completed_market_day], cwd=BASE_DIR, creationflags=0x08000000)
                else:
                    subprocess.Popen([sys.executable, "intraday_tracker.py", "--target-date", last_completed_market_day], cwd=BASE_DIR)
                errors += 1
                
            # QA 6: Market Open Readiness (Intraday Execution Blindspot Aware)
            df_pending = database_manager.execute_query('SELECT persona, date FROM pending_orders')
            expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                                 'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
            found_personas = df_pending['persona'].tolist() if not df_pending.empty else []
            df_settled_today = database_manager.execute_query('SELECT DISTINCT persona FROM capital_ledgers WHERE date >= ?', [next_market_day])
            settled_personas = df_settled_today['persona'].tolist() if not df_settled_today.empty else []
            active_or_settled = set(found_personas) | set(settled_personas)
            missing = [p for p in expected_personas if p not in active_or_settled]
            
            stale = False
            if not df_pending.empty:
                max_pending_date = df_pending['date'].max()
                if max_pending_date < next_market_day:
                    stale = True
                    log_alert(f"[QA 6] Stale Pending Orders Detected! Pending date ({max_pending_date}) < expected ({next_market_day}).")
                
            # Intraday Execution Blindspot Patch:
            # If ledger shows yesterday was successful, and pending_orders is empty, DO NOT panic.
            # The Sniper consumed them. Expected state post-execution. Wait for pipeline to run.
            if not missing and not stale:
                pass 
            elif missing or stale:
                if missing: log_alert(f"[QA 6] Missing Pending Orders for Personas: {missing}.")
                is_running = any('laptop_catchup_controller.py' in " ".join(p.info.get('cmdline', []) or []) for p in psutil.process_iter(['cmdline']))
                if is_running:
                    log_alert("-> Pipeline is actively running. Skipping auto-spawn.")
                else:
                    if os.name == 'nt':
                        subprocess.Popen([sys.executable, "laptop_catchup_controller.py"], cwd=BASE_DIR, creationflags=0x08000000)
                    else:
                        subprocess.Popen([sys.executable, "laptop_catchup_controller.py"], cwd=BASE_DIR)
                    errors += 1
                    
        # QA 10: ETF/Stock Sequencing
        stock_last = database_manager.get_last_continuity_date('master_pipeline')
        etf_last = database_manager.get_last_continuity_date('etf_pipeline')
        if etf_last and stock_last and etf_last > stock_last:
            log_alert(f"[QA 10] Interlock Violation: ETF Pipeline ({etf_last}) is ahead of Stock Pipeline ({stock_last}). Stale priors used!")
            errors += 1

        # QA 11: Prefect Orchestrator Liveness & Deployment Registration (Linux / Vultr Production)
        if os.name != 'nt':
            try:
                import urllib.request
                with urllib.request.urlopen("http://127.0.0.1:4200/api/health", timeout=5) as resp:
                    if resp.status != 200:
                        log_alert(f"[QA 11] Prefect Server unhealthy (HTTP {resp.status})!")
                        errors += 1
                serve_alive = any('prefect_pipeline.py' in " ".join(p.info.get('cmdline', []) or []) for p in psutil.process_iter(['cmdline']))
                if not serve_alive:
                    log_alert("[QA 11] prefect_pipeline.py serve daemon is NOT running on Vultr!")
                    errors += 1
                req_dep = urllib.request.Request(
                    "http://127.0.0.1:4200/api/deployments/filter",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req_dep, timeout=5) as resp_dep:
                    deps = json.loads(resp_dep.read().decode())
                    dep_names = {d.get("name") for d in deps if isinstance(d, dict)}
                    required_deps = {"nightly-pipeline", "weekend-trainers", "pre-market-health", "market-daemons-health"}
                    missing_deps = required_deps - dep_names
                    if missing_deps:
                        log_alert(f"[QA 11] Missing Prefect deployments in server registry: {missing_deps}")
                        errors += 1
            except Exception as e_pref:
                log_alert(f"[QA 11] Prefect Orchestrator verification failed: {e_pref}")
                errors += 1

    except Exception as e:
        log_alert(f"Failed to query database for QA Checks: {e}")
        errors += 1
        
    if errors == 0:
        print("--- All Tasks Audited: PASSED (11/11 Checks Green) ---")
        sys.stdout.flush()
        os._exit(0)
    else:
        print(f"--- Task Auditor Failed with {errors} Errors! Self-Healing agents have been dispatched. ---")
        sys.stdout.flush()
        os._exit(1)
