import sys
with open('preflight_check.py', 'r') as f:
    content = f.read()

patch = """
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
"""

# Replace the old patch with the new self-healing patch
import re
new_content = re.sub(r'# --- MARKET OPEN READINESS DIRECTIVE ENFORCEMENT ---.*?except Exception as e:\n    print\(f"\[WARNING\] Could not execute Market Open Readiness check: \{e\}"\)\n', patch, content, flags=re.DOTALL)

with open('preflight_check.py', 'w') as f:
    f.write(new_content)
