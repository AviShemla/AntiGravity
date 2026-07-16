import pandas as pd
import numpy as np
import os
import json
import sqlite3
import yfinance as yf
from datetime import datetime
from failover_downloader import download_ticker_with_failover

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
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
        if date_str in df.index.strftime('%Y-%m-%d').values:
            idx = list(df.index.strftime('%Y-%m-%d')).index(date_str)
            if idx > 0:
                prev_close = df['Close'].iloc[idx-1]
                curr_close = df['Close'].iloc[idx]
                return (curr_close - prev_close) / prev_close
    except Exception as e:
        print(f"Error fetching return for {ticker}: {e}")
    return 0.0

def run_tracker(target_date):
    print(f"--- Running Prod vs Shadow Tracker for {target_date} ---")
    state = load_state()
    
    if target_date <= state["last_date"]:
        print(f"Date {target_date} already processed. Skipping.")
        return
        
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
    if os.path.exists(MASTER_CSV):
        df.to_csv(MASTER_CSV, mode='a', header=False, index=False)
    else:
        df.to_csv(MASTER_CSV, index=False)
        
    trans_csv = os.path.join(BASE_DIR, "Shadow_Transformer_Scorecard.csv")
    v1_csv = os.path.join(DATA_DIR, "Sandbox_V1_Classic_Scorecard.csv")
    
    if os.path.exists(trans_csv):
        tdf = pd.read_csv(trans_csv)
        if not tdf.empty:
            # FIX: Filter by engine type instead of just taking the first row
            trans_rows = tdf[tdf['Engine'] == 'StockBrain']
            if not trans_rows.empty:
                state["holdings_transformer"] = trans_rows.iloc[0]["Ticker"]
            
            lstm_rows = tdf[tdf['Engine'] == 'LSTM_Shadow_V2']
            if not lstm_rows.empty:
                state["holdings_lstm"] = lstm_rows.iloc[0]["Ticker"]
            
    if os.path.exists(v1_csv):
        v1df = pd.read_csv(v1_csv)
        if not v1df.empty:
            state["holdings_v1"] = v1df.iloc[0]["Ticker"]
            
    state["last_date"] = target_date
    save_state(state)
    print(f"Saved stats: Prod=${prod_equity}, Trans=${state['Transformer']:.2f}, V1=${state['V1_Classic']:.2f}, LSTM=${state['LSTM_Shadow']:.2f}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_tracker(sys.argv[1])
    else:
        run_tracker(datetime.now().strftime("%Y-%m-%d"))
    os._exit(0)
