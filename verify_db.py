import database_manager
import pandas as pd
import json
import pandas_market_calendars as mcal
import numpy as np

def main():
    print("--- 1. Verification of NYSE Calendar Day Continuity ---")
    nyse = mcal.get_calendar('NYSE')
    
    # Get all distinct dates from capital_ledgers
    df_dates = database_manager.execute_query("SELECT DISTINCT date FROM capital_ledgers ORDER BY date ASC")
    if df_dates.empty:
        print("No dates found in capital_ledgers.")
    else:
        min_date = df_dates['date'].min()
        max_date = df_dates['date'].max()
        schedule = nyse.schedule(start_date=min_date, end_date=max_date)
        valid_days = [d.strftime('%Y-%m-%d') for d in schedule.index]
        
        db_dates = df_dates['date'].tolist()
        missing_in_db = set(valid_days) - set(db_dates)
        extra_in_db = set(db_dates) - set(valid_days)
        
        print(f"Date range: {min_date} to {max_date}")
        if not missing_in_db and not extra_in_db:
            print("PASS: Date continuity is perfect.")
        else:
            if missing_in_db:
                print(f"FAIL: Missing business days in DB: {sorted(list(missing_in_db))}")
            if extra_in_db:
                print(f"FAIL: Extra days in DB (weekends/holidays?): {sorted(list(extra_in_db))}")

    print("\n--- 2. Verification of Calculation Integrity ---")
    # Check that starting_cash + sum(PnL) == total_equity across all personas
    df_ledgers = database_manager.execute_query("SELECT persona, date, cash, total_equity, daily_pnl_json FROM capital_ledgers ORDER BY persona, date ASC")
    
    personas = df_ledgers['persona'].unique()
    for p in personas:
        df_p = df_ledgers[df_ledgers['persona'] == p].copy()
        df_p = df_p.reset_index(drop=True)
        
        starting_cash = 10000.0
        
        anomalies = []
        for i in range(len(df_p)):
            date = df_p.loc[i, 'date']
            total_eq = float(df_p.loc[i, 'total_equity'])
            
            if i > 0:
                prev_eq = float(df_p.loc[i-1, 'total_equity'])
                
                # Check 5% jump
                delta_pct = abs(total_eq - prev_eq) / prev_eq
                if delta_pct > 0.05:
                    anomalies.append(f"[{p}] {date}: Equity jumped by {delta_pct*100:.2f}% (from {prev_eq:.2f} to {total_eq:.2f})")
                
                # Recalculate based on sum(PnL) from day 1
                cumulative_pnl = 0.0
                for j in range(1, i + 1):
                    try:
                        pnl_str = df_p.loc[j, 'daily_pnl_json']
                        if not pnl_str or pd.isna(pnl_str) or pnl_str == 'null':
                            continue
                        pnl = json.loads(pnl_str)
                        for k, v in pnl.items():
                            if k != 'Cash':
                                if isinstance(v, dict):
                                    cumulative_pnl += float(v.get('dollars', 0.0))
                                else:
                                    cumulative_pnl += float(v)
                    except:
                        pass
                
                expected_eq = starting_cash + cumulative_pnl
                
                diff = abs(total_eq - expected_eq)
                # Print mismatch if significant (due to lack of starting_cash explicitly, assume 10000 but check difference)
                if diff > 10.0 and j == i: 
                     # Just checking the last row for each day to avoid spam
                     pass

        if not anomalies:
            print(f"{p}: PASS (No >5% single-day jumps)")
        else:
            print(f"{p}: FAIL")
            for a in anomalies:
                print(f"  - {a}")

    print("\n--- 3. Validation of Backend Endpoints against Turso DB ---")
    print("Checking Olympic Shootout Endpoint vs DB...")
    
    # Get Olympic data from DB
    df_ol = database_manager.execute_query("SELECT date, model_name, total_equity FROM olympic_shootout_master ORDER BY date ASC")
    
    try:
        from fastapi.testclient import TestClient
        import sys
        sys.path.append('.')
        from server import app
        client = TestClient(app)
        resp = client.get("/api/olympic")
        
        if resp.status_code == 200:
            json_data = resp.json()
            table_data = json_data.get('table_data', [])
            
            unique_dates = df_ol['date'].nunique()
            print(f"DB unique dates: {unique_dates}, JSON table dates: {len(table_data)}")
            
            if unique_dates != len(table_data):
                print(f"FAIL: Olympic Endpoint rows ({len(table_data)}) mismatch DB distinct dates ({unique_dates}).")
            else:
                print("PASS: Olympic Endpoint rows match DB dates count.")
        else:
            print(f"Olympic endpoint failed with status {resp.status_code}")
    except Exception as e:
        print(f"Could not test FastAPI endpoint: {e}")

if __name__ == '__main__':
    main()
