import os
import sys
import subprocess
import pandas as pd
import datetime
import json

try:
    import pandas_market_calendars as mcal
except ImportError:
    mcal = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
python_exe = sys.executable

def get_missed_dates(pipeline_name):
    if mcal is None:
        print("pandas_market_calendars missing. Falling back to today.")
        return [pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d')]
        
    last_completed = database_manager.get_last_continuity_date(pipeline_name)
    
    nyse = mcal.get_calendar('NYSE')
    now = pd.Timestamp.now(tz='America/New_York')
    
    # 1. Calculate past sessions based on market close
    schedule = nyse.schedule(start_date=(now - pd.Timedelta(days=7)).strftime('%Y-%m-%d'), end_date=(now + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
    past_sessions = schedule[schedule['market_close'] < now]
    
    if past_sessions.empty:
        return []
        
    last_closed_session = past_sessions.iloc[-1].name.strftime('%Y-%m-%d')
    
    # 2. Calculate historical missed sessions
    if not last_completed:
        missed_dates = [last_closed_session]
    else:
        missed_sessions = past_sessions[past_sessions.index > pd.to_datetime(last_completed)]
        missed_dates = [d.strftime('%Y-%m-%d') for d in missed_sessions.index]
        
    # 3. Check if today's predictions are staged
    future_schedule = nyse.schedule(start_date=last_closed_session, end_date=(now + pd.Timedelta(days=7)).strftime('%Y-%m-%d'))
    if len(future_schedule) > 1:
        target_prediction_date = future_schedule.iloc[1].name.strftime('%Y-%m-%d')
    else:
        target_prediction_date = (pd.to_datetime(last_closed_session) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        
    db_staged_date = None
    try:
        df = database_manager.execute_query("SELECT date FROM pending_orders LIMIT 1")
        if not df.empty:
            db_staged_date = df.iloc[0]['date']
    except Exception as e:
        print(f"Error checking pending orders: {e}")
        
    if db_staged_date != target_prediction_date and last_closed_session not in missed_dates:
        print(f"[ARCHITECTURAL FIX] Pending orders for {target_prediction_date} are NOT staged yet. Adding {last_closed_session} to execution list.")
        missed_dates.append(last_closed_session)
        
    return missed_dates

def mark_completed(pipeline_name, date_str):
    database_manager.update_continuity(pipeline_name, date_str)

def send_error_email(subject, msg):
    try:
        from daily_pipeline import send_outlook_email
        send_outlook_email(subject, f"<pre>{msg}</pre>")
    except:
        pass

def catchup_master_pipeline():
    print("=== AntiGravity Master Pipeline Catch-Up Protocol ===")
    missed_dates = get_missed_dates('master_pipeline')
    
    if not missed_dates:
        print("No historical days missed. Master Pipeline is completely up to date!")
        return
        
    print(f"[{len(missed_dates)} Missed Days Detected] -> Catch-Up Protocol Initiated")
    
    try:
        from failover_downloader import clear_warnings, clear_quarantined_tickers
        clear_warnings()
        clear_quarantined_tickers()
    except Exception as e:
        print(f"Warning: Could not clear warnings: {e}")
        
    print("\nStep 1: Running SPY.py to fetch latest master data...")
    res = subprocess.run([python_exe, os.path.join(BASE_DIR, "SPY.py")], cwd=BASE_DIR)
    if res.returncode != 0:
        error_msg = f"Pipeline Aborted. SPY.py failed with Exit Code: {res.returncode}"
        print(error_msg)
        send_error_email("AntiGravity Error: SPY.py Failed", error_msg)
        os._exit(1)
        
    for idx, target_date in enumerate(missed_dates):
        is_last = (idx == len(missed_dates) - 1)
        print(f"\n==============================================")
        print(f"=== MASTER PIPELINE FOR DATE: {target_date} ===")
        print(f"==============================================\n")
        
        # 0.5 Weekly Fundamentals Extraction
        if pd.to_datetime(target_date).weekday() == 5: # Saturday
            print("\n--> Running Weekend Fundamentals Extraction (Saturday)...")
            subprocess.run([python_exe, os.path.join(BASE_DIR, "extract_fundamentals.py")], cwd=BASE_DIR)

        # 1. Meta Predictor Tracker (Alpha Recalibration)
        if pd.to_datetime(target_date).weekday() == 6: # Sunday
            print("\n--> Running Meta-Predictor Tracker (Sunday Alpha Recalibration)...")
            subprocess.run([python_exe, os.path.join(BASE_DIR, "meta_predictor_tracker.py")], cwd=BASE_DIR)
            
        # 1.5 Deep Learning Inference Engine
        print("\n--> Running Deep Learning AI Inference Engine (V2 Upgrade)...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "daily_dl_inference.py"), "--target-date", target_date], cwd=BASE_DIR, check=True)
            
        # 2. Bayesian Scorecard Formatted
        print("\n--> Running export_bayesian_scorecard_formatted.py...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "export_bayesian_scorecard_formatted.py"), "--target-date", target_date], cwd=BASE_DIR, check=True)
        
        # 3. QA Models Bounds
        print("\n--> Running qa_models.py...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "qa_models.py")], cwd=BASE_DIR) # it was qa_models.py
        
        # Get next business day for prediction target
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(start_date=target_date, end_date=(pd.to_datetime(target_date) + pd.Timedelta(days=7)).strftime('%Y-%m-%d'))
        prediction_date = schedule.iloc[1].name.strftime('%Y-%m-%d') if len(schedule) > 1 else (pd.to_datetime(target_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

        # 4. Virtual Broker
        print("\n--> Running virtual_broker.py...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "virtual_broker.py"), "--target-date", prediction_date], cwd=BASE_DIR, check=True)
        
        # 5. Intraday Tracker (Executes EOD)
        today_ny = pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d')
        if prediction_date < today_ny or (prediction_date == today_ny and pd.Timestamp.now(tz='America/New_York').hour >= 16):
            print("\n--> Running intraday_tracker.py (EOD execution)...")
            subprocess.run([python_exe, os.path.join(BASE_DIR, "intraday_tracker.py"), "--target-date", prediction_date], cwd=BASE_DIR, check=True)
        else:
            print(f"\n--> Skipping intraday_tracker.py (Prediction Date {prediction_date} is Today and Market hasn't closed yet)...")
        
        # 6. Export Excel Reports
        print("\n--> Running export_broker_excel_report.py...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "export_broker_excel_report.py")], cwd=BASE_DIR)
        
        # 6.5 Financial QA Audit
        print("\n--> Running Financial QA Audit...")
        fin_qa = subprocess.run([python_exe, os.path.join(BASE_DIR, "qa_financial_audit.py")], cwd=BASE_DIR)
        if fin_qa.returncode != 0:
            print("FATAL: Financial Audit Failed! Aborting Catchup!")
            os._exit(1)
            
        # 7. QA Blacklist
        qa_script = os.path.join(BASE_DIR, "qa_blacklist.py")
        if os.path.exists(qa_script):
            print("\n--> Running QA Blacklist Audit...")
            subprocess.run([python_exe, qa_script], cwd=BASE_DIR)
            
        # 8. Mark Complete
        mark_completed('master_pipeline', target_date)
        
        print("\n--> Running Olympic Shootout Backtests (Generating New Chart Dots)...\n")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "run_backtests.py")], cwd=BASE_DIR)

        # 9. Shadow Sandboxes
        print("\n--> Running V1 Classic Shadow Sandbox synchronously for historical backfill...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "sandbox_v1_classic.py"), "--target-date", target_date], cwd=BASE_DIR)
        
        # 10. Update Shadow Tracker
        print(f"\n--> Updating Prod vs Shadow Tracker for {target_date}...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "prod_vs_shadow_tracker.py"), target_date], cwd=BASE_DIR)


    print("\nMaster Pipeline Catch-Up Complete!")

def catchup_etf_pipeline():
    print("=== AntiGravity ETF Pipeline Catch-Up Protocol ===")
    missed_dates = get_missed_dates('etf_pipeline')
    
    if not missed_dates:
        print("No historical days missed. ETF Pipeline is completely up to date!")
        return
        
    print(f"[{len(missed_dates)} Missed Days Detected] -> ETF Catch-Up Protocol Initiated")
    
    for idx, target_date in enumerate(missed_dates):
        is_last = (idx == len(missed_dates) - 1)
        print(f"\n==============================================")
        print(f"=== ETF PIPELINE FOR DATE: {target_date} ===")
        print(f"==============================================\n")
        
        # 0. Generate Dynamic ETFs (Run Screener)
        print("\n--> [PRE-FLIGHT] Running Dynamic ETF Screener...")
        try:
            subprocess.run([python_exe, os.path.join(BASE_DIR, "generate_dynamic_etfs.py")], cwd=BASE_DIR, timeout=300)
        except Exception as e:
            print(f"ETF Screener failed: {e}")

        # 1. Export ETF Scorecards
        try:
            with open(os.path.join(BASE_DIR, 'financial_data', 'Dynamic_Target_ETFs.json'), 'r') as f:
                TARGET_ETFS = json.load(f)
        except Exception:
            TARGET_ETFS = ['XLK', 'XLV', 'XLY', 'XLF', 'XLC', 'XLI', 'XLE', 'XLP', 'XLU', 'XLRE', 'XLB']
            
        if not TARGET_ETFS: TARGET_ETFS = ['XLK'] # Fallback failsafe
        
        import concurrent.futures

        def process_etf_pipeline(etf):
            print(f"\n--> [PARALLEL THREAD] Processing ETF Pipeline for {etf}...")
            try:
                subprocess.run([python_exe, os.path.join(BASE_DIR, "build_etf_hybrid_matrix.py"), etf], cwd=BASE_DIR, check=True)
                subprocess.run([python_exe, os.path.join(BASE_DIR, "run_etf_hybrid_screener.py"), etf], cwd=BASE_DIR, check=True)
                subprocess.run([python_exe, os.path.join(BASE_DIR, "export_etf_scorecard.py"), etf, "--target-date", target_date], cwd=BASE_DIR, check=True)
                return True
            except subprocess.CalledProcessError as e:
                print(f"!!! ETF Pipeline Failed for {etf}: {e}")
                return False

        print("\n--- Spawning ETF Subprocesses (Parallel Capped at 3 Threads) ---")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(process_etf_pipeline, etf) for etf in TARGET_ETFS]
            for future in concurrent.futures.as_completed(futures):
                future.result()

            
        # 2. Compile Scorecards
        print("\n--> Compiling All ETF Scorecards...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "compile_etf_scorecards.py")], cwd=BASE_DIR)
        
        # 3. ETF Virtual Broker
        print("\n--> Running etf_virtual_broker.py...")
        # Get next business day
        nyse = mcal.get_calendar('NYSE')
        schedule = nyse.schedule(start_date=target_date, end_date=(pd.to_datetime(target_date) + pd.Timedelta(days=7)).strftime('%Y-%m-%d'))
        prediction_date = schedule.iloc[1].name.strftime('%Y-%m-%d') if len(schedule) > 1 else (pd.to_datetime(target_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        
        subprocess.run([python_exe, os.path.join(BASE_DIR, "etf_virtual_broker.py"), "--target-date", prediction_date], cwd=BASE_DIR, check=True)
        
        # 4. Intraday Tracker (Executes EOD)
        today_ny = pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d')
        if prediction_date < today_ny or (prediction_date == today_ny and pd.Timestamp.now(tz='America/New_York').hour >= 16):
            print("\n--> Running intraday_tracker.py (EOD execution)...")
            subprocess.run([python_exe, os.path.join(BASE_DIR, "intraday_tracker.py"), "--target-date", prediction_date], cwd=BASE_DIR, check=True)
        else:
            print(f"\n--> Skipping intraday_tracker.py (Prediction Date {prediction_date} is Today and Market hasn't closed yet)...")
        
        # 5. Export ETF Broker Excel
        print("\n--> Running export_etf_broker_excel.py...")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "export_etf_broker_excel.py")], cwd=BASE_DIR)
        
        # 5.5 Financial QA Audit
        print("\n--> Running ETF Financial QA Audit...")
        fin_qa = subprocess.run([python_exe, os.path.join(BASE_DIR, "qa_financial_audit.py")], cwd=BASE_DIR)
        if fin_qa.returncode != 0:
            print("FATAL: Financial Audit Failed! Aborting ETF Catchup!")
            subprocess.run([python_exe, os.path.join(BASE_DIR, "send_email_notification.py"), "🚨 CRITICAL: ETF QA Audit Failed", "The Financial QA Auditor caught a mathematical discrepancy and aborted the ETF pipeline. Check server logs immediately."], cwd=BASE_DIR)
            os._exit(1)
            
        # 6. Mark Complete
        mark_completed('etf_pipeline', target_date)
        
        if is_last:
            pass # Sandbox logic moved to Master Pipeline loop for chronological backfilling

    print("\nETF Pipeline Catch-Up Complete!")

def catchup_everything_and_email():
    catchup_master_pipeline()
    catchup_etf_pipeline()
    
    print("\n==============================================")
    print("=== FINAL QA GATE (100% GREEN REQUIREMENT) ===")
    print("==============================================\n")
    fin_qa = subprocess.run([python_exe, os.path.join(BASE_DIR, "system_qa_auditor.py")], cwd=BASE_DIR)
    if fin_qa.returncode != 0:
        print("FATAL: Final QA Audit Failed! The system is NOT 100% green.")
        print("Emails will NOT be dispatched to prevent broken reporting.")
        subprocess.run([python_exe, os.path.join(BASE_DIR, "send_email_notification.py"), "🚨 CRITICAL: Master QA Audit Failed", "The Final QA Auditor caught a mathematical discrepancy and aborted the master pipeline. Check server logs immediately."], cwd=BASE_DIR)
        os._exit(1)
        
    print("\nQA Audit Passed: 100% Green! Dispatching perfectly synchronized emails...")
    print("\n--> Sending Executive Brief...\n")
    subprocess.run([python_exe, os.path.join(BASE_DIR, "executive_brief.py")], cwd=BASE_DIR)
    subprocess.run([python_exe, os.path.join(BASE_DIR, "send_master_email.py")], cwd=BASE_DIR)
    subprocess.run([python_exe, os.path.join(BASE_DIR, "send_etf_email.py")], cwd=BASE_DIR)
    subprocess.run([python_exe, os.path.join(BASE_DIR, "send_championship_email.py")], cwd=BASE_DIR)
    print("All emails dispatched successfully!")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "etf":
        catchup_etf_pipeline()
    elif len(sys.argv) > 1 and sys.argv[1] == "master":
        catchup_master_pipeline()
    else:
        catchup_everything_and_email()
    os._exit(0)
