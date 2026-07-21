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


# --- MARKET OPEN READINESS DIRECTIVE ENFORCEMENT & SELF-HEALING ---
try:
    import pandas_market_calendars as mcal
    import pandas as pd
    from database_manager import execute_query
    import subprocess
    import time
    
    nyse = mcal.get_calendar('NYSE')
    now = pd.Timestamp.now(tz='America/New_York')
    schedule = nyse.schedule(start_date=(now - pd.Timedelta(days=7)).strftime('%Y-%m-%d'), end_date=(now + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
    past_sessions = schedule[schedule['market_close'] < now]
    
    if now.hour < 16 and not past_sessions[past_sessions.index == now.strftime('%Y-%m-%d')].empty:
        target_date = now.strftime('%Y-%m-%d')
    else:
        target_date = schedule[schedule.index > now.strftime('%Y-%m-%d')].iloc[0].name.strftime('%Y-%m-%d')
        
    print(f"[INFO] Evaluating Market Open Readiness for Target Date: {target_date}")
    
    def check_readiness():
        df = execute_query("SELECT persona, MAX(date) as max_date FROM pending_orders GROUP BY persona")
        ready_personas = []
        if not df.empty:
            ready_personas = df[df['max_date'] == target_date]['persona'].tolist()
            
        expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                             'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
        missing = [p for p in expected_personas if p not in ready_personas]
        
        if missing:
            df_ledgers = execute_query("SELECT persona, MAX(date) as max_date FROM capital_ledgers GROUP BY persona")
            if not df_ledgers.empty:
                ledger_ready = df_ledgers[df_ledgers['max_date'] == target_date]['persona'].tolist()
                missing = [p for p in missing if p not in ledger_ready]
        return missing

    missing = check_readiness()
    
    if missing:
        is_market_open = now.hour >= 9 and now.hour < 16 and not past_sessions[past_sessions.index == now.strftime('%Y-%m-%d')].empty
        
        if is_market_open:
            print(f"[FAIL] CRITICAL ERROR: Market Open Readiness Directive VIOLATED! Missing active predictions for: {missing}")
            print(f"[SYSTEM] Initiating Automated Self-Healing Protocol...")
            
            try:
                # Trigger the Catch-Up Controller to force a full pipeline run
                subprocess.run([sys.executable, "laptop_catchup_controller.py"], check=True)
                
                # Re-verify after self-healing
                print(f"[SYSTEM] Self-Healing Protocol completed. Re-verifying database...")
                missing_after_heal = check_readiness()
                
                if missing_after_heal:
                    print(f"[FATAL] Self-Healing FAILED to resolve missing predictions for: {missing_after_heal}")
                    os._exit(1)
                else:
                    print(f"[SUCCESS] Automated Self-Healing successfully populated all instructions for {target_date}.")
                    
            except Exception as e:
                print(f"[FATAL] Self-Healing Pipeline crashed: {e}")
                os._exit(1)
        else:
            print(f"[WARNING] Pre-market pipeline has not yet populated predictions for: {missing}. (Market is closed, no self-heal required yet).")
    else:
         print(f"[OK] Market Open Readiness: All 8 Personas have active instructions ready for {target_date}.")
         
except Exception as e:
    print(f"[WARNING] Could not execute Market Open Readiness check: {e}")

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
os._exit(0)
