import pandas as pd
import numpy as np
import os
import json
import sqlite3
import yfinance as yf
from datetime import datetime
from failover_downloader import download_ticker_with_failover

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "financial_data")
MASTER_CSV = os.path.join(DATA_DIR, "Prod_vs_Shadow_Results_MASTER.csv")
STATE_JSON = os.path.join(DATA_DIR, "prod_shadow_state.json")

def get_prod_equity(date_str):
    try:
        import database_manager
        df = database_manager.execute_query(f"SELECT total_equity FROM capital_ledgers WHERE persona='BallsForBrains' AND date LIKE '{date_str}%'")
        if not df.empty:
            return float(df['total_equity'].iloc[-1])
        
        # FIX: If today's exact balance isn't populated yet, fallback to the most recent known balance instead of flatlining at 10000.00.
        df_latest = database_manager.execute_query("SELECT total_equity FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 1")
        if not df_latest.empty:
            return float(df_latest['total_equity'].iloc[-1])
    except:
        pass
    return 10000.0

def load_state():
    if os.path.exists(STATE_JSON):
        with open(STATE_JSON, 'r') as f:
            st = json.load(f)
            if "LSTM_Shadow" not in st: st["LSTM_Shadow"] = 10000.0
            if "holdings_lstm" not in st: st["holdings_lstm"] = None
            return st
    return {
        "Transformer": 10000.0,
        "V1_Classic": 10000.0,
        "LSTM_Shadow": 10000.0,
        "last_date": "2026-06-19",
        "holdings_transformer": None,
        "holdings_v1": None,
        "holdings_lstm": None
    }

def save_state(state):
    with open(STATE_JSON, 'w') as f:
        json.dump(state, f)

def get_return(ticker, date_str):
    if not ticker: return 0.0
    try:
        df = download_ticker_with_failover(ticker, period="5d")
        if df is None or df.empty: return 0.0
        
        # ZERO-TRUST SELF-HEALING: Forward-fill any NaN values before calculating returns.
        # This guarantees that if yfinance drops a day (e.g., Friday), the system bridges the gap 
        # using Thursday's price, and mathematically captures the exact missing delta on Monday.
        if 'Close' in df.columns:
            df['Close'] = df['Close'].ffill()
            
        if date_str in df.index.strftime('%Y-%m-%d').values:
            idx = list(df.index.strftime('%Y-%m-%d')).index(date_str)
            if idx > 0:
                prev_close = df['Close'].iloc[idx-1]
                curr_close = df['Close'].iloc[idx]
                
                import math
                if math.isnan(curr_close) or math.isnan(prev_close):
                    print(f"Zero-Trust Alert: Unrecoverable NaN for {ticker} on {date_str}. Enforcing flat return.")
                    return 0.0
                    
                ret = (curr_close - prev_close) / prev_close
                if ret > 0.2:
                    print(f"Zero-Trust Alert: Unnatural spike of {ret*100}% for {ticker}. Capping return to 0.")
                    return 0.0
                return ret
    except Exception as e:
        print(f"Error fetching return for {ticker}: {e}")
    return 0.0

def run_tracker(target_date):
    print(f"--- Running Prod vs Shadow Tracker for {target_date} ---")
    state = load_state()
    
    # Always compute/update row for target_date
        
    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
    if dt_obj.weekday() >= 5:
        print(f"Date {target_date} is a weekend. The market is closed. Skipping.")
        return
        
    if state.get("last_date") == target_date:
        print(f"Idempotency Guard: State already calculated for {target_date}. Skipping multiplication.")
    else:
        ret_trans = get_return(state["holdings_transformer"], target_date)
        ret_v1 = get_return(state["holdings_v1"], target_date)
        ret_lstm = get_return(state["holdings_lstm"], target_date)
        
        state["Transformer"] *= (1 + ret_trans)
        state["V1_Classic"] *= (1 + ret_v1)
        state["LSTM_Shadow"] *= (1 + ret_lstm)
    
    prod_equity = get_prod_equity(target_date)
    
    row = {
        "Date": target_date,
        "Prod": prod_equity,
        "Shadow_Transformer": round(state["Transformer"], 2),
        "Sandbox_V1": round(state["V1_Classic"], 2),
        "Shadow_LSTM": round(state["LSTM_Shadow"], 2)
    }
    
    df = pd.DataFrame([row])
    if os.path.exists(MASTER_CSV) and os.path.getsize(MASTER_CSV) > 0:
        existing_df = pd.read_csv(MASTER_CSV)
        merged = pd.concat([existing_df, df], ignore_index=True)
        merged = merged.drop_duplicates(subset=['Date'], keep='last')
        merged.to_csv(MASTER_CSV, index=False)
    else:
        df.to_csv(MASTER_CSV, index=False)

    # SOURCE OF TRUTH: Also write to Turso DB prod_vs_shadow_master
    try:
        import database_manager
        col_map = {
            "Prod": "PROD_Bayesian_SV",
            "Shadow_Transformer": "Shadow_Transformer",
            "Sandbox_V1": "Sandbox_V1",
            "Shadow_LSTM": "Shadow_LSTM"
        }
        for csv_col, model_name in col_map.items():
            val = row.get(csv_col)
            if val is not None:
                database_manager.execute_write("""
                    INSERT INTO prod_vs_shadow_master (date, model_name, total_equity)
                    VALUES (?, ?, ?)
                    ON CONFLICT(date, model_name) DO UPDATE SET total_equity=excluded.total_equity
                """, [target_date, model_name, float(val)])
        print(f"  [DB] Prod vs Shadow row for {target_date} written to Turso DB")
    except Exception as e_db:
        print(f"  [DB WARNING] Failed to write Prod vs Shadow to Turso DB: {e_db}")


        
    # 100% TURSO DB BACKED: Determine active holdings strictly from Turso DB tables
    try:
        import database_manager
        # Query top ticker from Turso DB for Transformer/LSTM
        df_db_sc = database_manager.execute_query(f"SELECT ticker FROM etf_scorecards_master WHERE date LIKE '{target_date}%' ORDER BY prob DESC LIMIT 5")
        if not df_db_sc.empty:
            state["holdings_transformer"] = df_db_sc.iloc[0]["ticker"]
            if len(df_db_sc) > 1:
                state["holdings_lstm"] = df_db_sc.iloc[1]["ticker"]
            else:
                state["holdings_lstm"] = df_db_sc.iloc[0]["ticker"]
                
        # Query pending orders / top momentum for Sandbox V1
        df_db_v1 = database_manager.execute_query(f"SELECT target_holdings_json FROM pending_orders WHERE persona = 'BallsForBrains' AND date LIKE '{target_date}%'")
        if not df_db_v1.empty and df_db_v1.iloc[0]['target_holdings_json']:
            h_v1 = json.loads(df_db_v1.iloc[0]['target_holdings_json'])
            t_v1 = [k for k in h_v1.keys() if k != 'CASH']
            if t_v1:
                state["holdings_v1"] = t_v1[0]
    except Exception as e_holdings:
        print(f"  [DB HOLDINGS ERROR] Failed to fetch holdings from Turso DB: {e_holdings}")
            
    state["last_date"] = target_date
    save_state(state)
    print(f"Saved stats: Prod=${prod_equity}, Trans=${state['Transformer']:.2f}, V1=${state['V1_Classic']:.2f}, LSTM=${state['LSTM_Shadow']:.2f}")
    
    # --- Sync Dashboard CSVs to Vultr (Laptop Only) ---
    if os.name == 'nt':
        print("\n--- Deploying Updated CSV to Vultr Dashboard ---")
        try:
            import subprocess, sys
            subprocess.run([sys.executable, "fast_deploy.py"])
        except Exception as e:
            print(f"Deploy failed: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_tracker(sys.argv[1])
    else:
        print("Requires target date")

import sys; sys.stdout.flush(); os._exit(0)
