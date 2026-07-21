import sys
with open('system_qa_auditor.py', 'r') as f:
    content = f.read()

patch = """
        from database_manager import execute_query
        
        # --- NEW STRICT QA: Target Date Enforcement in Capital Ledgers ---
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar('NYSE')
        now = pd.Timestamp.now(tz='America/New_York')
        schedule = nyse.schedule(start_date=(now - pd.Timedelta(days=7)).strftime('%Y-%m-%d'), end_date=(now + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        past_sessions = schedule[schedule['market_close'] < now]
        # Calculate the TARGET PREDICTION DATE (which is the next business day after the last close, or today if market is open)
        # Actually, simpler: just get the target date the virtual_broker used
        # Since this QA runs after Nightly Pipeline, the DB MUST have the exact target date for all 8 personas.
        # We will dynamically calculate it.
        if now.hour < 16 and not past_sessions[past_sessions.index == now.strftime('%Y-%m-%d')].empty:
             expected_target = now.strftime('%Y-%m-%d')
        else:
             expected_target = schedule[schedule.index > now.strftime('%Y-%m-%d')].iloc[0].name.strftime('%Y-%m-%d')
             
        # Check ledgers instead of volatile pending_orders
        query = "SELECT persona, MAX(date) as max_date FROM capital_ledgers GROUP BY persona"
        df_ledgers = execute_query(query)
        if df_ledgers.empty:
            print(" !!! FATAL: No capital ledgers found for ANY persona!")
            return False
            
        expected_personas = ['Conservative', 'Neutral', 'BallsForBrains', 'Dynamic', 
                             'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains', 'ETF_Dynamic']
                             
        missing_or_stale = []
        for p in expected_personas:
            p_data = df_ledgers[df_ledgers['persona'] == p]
            if p_data.empty or p_data.iloc[0]['max_date'] != expected_target:
                missing_or_stale.append(p)
                
        if missing_or_stale:
            print(f" !!! FAIL: Missing or Stale Ledger Dates (Expected {expected_target}) for personas: {missing_or_stale}")
            return False
            
        print(f" -> PASS: All {len(expected_personas)} Personas successfully verified in Capital Ledgers for target date {expected_target}.")
        return True
"""
# Replace the block
content = content.replace('        from database_manager import execute_query\n        query = "SELECT DISTINCT persona FROM pending_orders"', patch.strip())
with open('system_qa_auditor.py', 'w') as f:
    f.write(content)
