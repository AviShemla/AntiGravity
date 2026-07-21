import sys
with open('preflight_check.py', 'r') as f:
    content = f.read()

patch = """
# Check Paths
if not os.path.exists(config.DATA_DIR):
    print(f"[FAIL] CRITICAL ERROR: Data directory missing: {config.DATA_DIR}")
    os._exit(1)
else:
    print(f"[OK] Data directory verified.")

# --- MARKET OPEN READINESS DIRECTIVE ENFORCEMENT ---
try:
    import pandas_market_calendars as mcal
    import pandas as pd
    from database_manager import execute_query
    
    nyse = mcal.get_calendar('NYSE')
    now = pd.Timestamp.now(tz='America/New_York')
    schedule = nyse.schedule(start_date=(now - pd.Timedelta(days=7)).strftime('%Y-%m-%d'), end_date=(now + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
    past_sessions = schedule[schedule['market_close'] < now]
    
    if now.hour < 16 and not past_sessions[past_sessions.index == now.strftime('%Y-%m-%d')].empty:
        target_date = now.strftime('%Y-%m-%d')
    else:
        target_date = schedule[schedule.index > now.strftime('%Y-%m-%d')].iloc[0].name.strftime('%Y-%m-%d')
        
    print(f"[INFO] Evaluating Market Open Readiness for Target Date: {target_date}")
    
    # We enforce readiness by ensuring ALL 8 Personas exist in pending_orders OR capital_ledgers with the target date
    # Normally preflight runs BEFORE market open, meaning virtual_broker should have already generated pending_orders
    # However, if the ML pipeline failed, it will be missing.
    df = execute_query("SELECT persona, MAX(date) as max_date FROM pending_orders GROUP BY persona")
    ready_personas = []
    if not df.empty:
        ready_personas = df[df['max_date'] == target_date]['persona'].tolist()
        
    expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                         'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
                         
    missing = [p for p in expected_personas if p not in ready_personas]
    
    # During market hours, the Sniper might have already deleted pending_orders and moved them to capital_ledgers
    if missing:
        df_ledgers = execute_query("SELECT persona, MAX(date) as max_date FROM capital_ledgers GROUP BY persona")
        if not df_ledgers.empty:
            ledger_ready = df_ledgers[df_ledgers['max_date'] == target_date]['persona'].tolist()
            missing = [p for p in missing if p not in ledger_ready]
            
    if missing:
        # If we are strictly during active market hours, this is a FATAL abort.
        if now.hour >= 9 and now.hour < 16 and not past_sessions[past_sessions.index == now.strftime('%Y-%m-%d')].empty:
            print(f"[FAIL] CRITICAL ERROR: Market Open Readiness Directive VIOLATED! Missing active predictions for: {missing}")
            os._exit(1)
        else:
            print(f"[WARNING] Pre-market pipeline has not yet populated predictions for: {missing}")
    else:
         print(f"[OK] Market Open Readiness: All 8 Personas have active instructions ready for {target_date}.")
         
except Exception as e:
    print(f"[WARNING] Could not execute Market Open Readiness check: {e}")
"""
content = content.replace("# Check Paths\nif not os.path.exists(config.DATA_DIR):\n    print(f\"[FAIL] CRITICAL ERROR: Data directory missing: {config.DATA_DIR}\")\n    os._exit(1)\nelse:\n    print(f\"[OK] Data directory verified.\")", patch.strip())

with open('preflight_check.py', 'w') as f:
    f.write(content)
