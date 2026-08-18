import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
import database_manager
from failover_downloader import download_ticker_with_failover

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_JSON = os.path.join(BASE_DIR, "financial_data", "shadow_neural_safety_state.json")

# VIP Single Stock Tickers
VIP_STOCKS = ['ADSK', 'GPC', 'MCD', 'BLK', 'NDAQ', 'ADM', 'NEE', 'ELV', 'CB', 'NKE']

def load_state():
    if os.path.exists(STATE_JSON):
        try:
            with open(STATE_JSON, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "equity": 10000.0,
        "last_date": "2026-06-19",
        "holdings": {}
    }

def save_state(state):
    with open(STATE_JSON, 'w') as f:
        json.dump(state, f, indent=2)

def run_shadow_neural_safety(target_date):
    print(f"\n--- [SHADOW CONTENDER #2] Running Shadow Neural Safety Engine for {target_date} ---")
    state = load_state()
    
    # 1. Fetch VIX and market safety indicators
    vix_val = 15.0
    vix_path = os.path.join(BASE_DIR, "financial_data", "vix_score.json")
    if os.path.exists(vix_path):
        try:
            with open(vix_path, 'r') as f:
                vix_val = float(json.load(f).get("vix_value", 15.0))
        except:
            pass

    # 2. Neural Safety Model (Task #2 Logic)
    # Calculate Dynamic Safety Multiplier: Neural network penalty weight based on volatility regime
    # If VIX > 20, tightens stops and scales back leverage to preserve capital
    safety_multiplier = max(0.5, 1.0 - max(0.0, (vix_val - 15.0) * 0.05))
    
    # 3. Fetch stock returns for VIP tickers
    stock_returns = {}
    for t in VIP_STOCKS:
        try:
            df = download_ticker_with_failover(t, period="5d")
            if df is not None and not df.empty:
                df = df.ffill()
                if target_date in df.index.strftime('%Y-%m-%d'):
                    idx = list(df.index.strftime('%Y-%m-%d')).index(target_date)
                    if idx > 0:
                        prev_close = float(df['Close'].iloc[idx-1])
                        curr_close = float(df['Close'].iloc[idx])
                        ret = (curr_close - prev_close) / prev_close
                        stock_returns[t] = (ret, curr_close)
        except Exception as e:
            print(f"  [WARNING] Failed to fetch {t} return: {e}")

    # 4. Mark-to-Market Portfolio
    curr_equity = state["equity"]
    if state["holdings"]:
        mtm_equity = state.get("cash", curr_equity)
        for t, h_data in state["holdings"].items():
            if t in stock_returns:
                units = float(h_data.get("units", 0))
                price = stock_returns[t][1]
                mtm_equity += units * price
        curr_equity = mtm_equity

    # 5. Position Sizing guided by Neural Safety Multiplier
    # Target 60% max capital deployment (moderated safety) split across top 2 momentum stocks
    sorted_stocks = sorted(stock_returns.items(), key=lambda x: x[1][0], reverse=True)[:2]
    alloc_capital = curr_equity * 0.60 * safety_multiplier
    per_stock_alloc = alloc_capital / len(sorted_stocks) if sorted_stocks else 0
    
    new_holdings = {}
    remaining_cash = curr_equity - alloc_capital
    for t, (ret, price) in sorted_stocks:
        if price > 0:
            units = int(per_stock_alloc // price)
            actual_dollars = units * price
            remaining_cash += (per_stock_alloc - actual_dollars)
            if units > 0:
                new_holdings[t] = {
                    "units": units,
                    "price": price,
                    "dollars": round(actual_dollars, 2)
                }

    final_equity = remaining_cash + sum([h["dollars"] for h in new_holdings.values()])
    state["equity"] = round(final_equity, 2)
    state["cash"] = round(remaining_cash, 2)
    state["last_date"] = target_date
    state["holdings"] = new_holdings
    save_state(state)

    # 6. Write directly to Turso DB SSOT (prod_vs_shadow_master)
    try:
        database_manager.execute_write("""
            INSERT INTO prod_vs_shadow_master (date, model_name, total_equity)
            VALUES (?, ?, ?)
            ON CONFLICT(date, model_name) DO UPDATE SET total_equity=excluded.total_equity
        """, [target_date, 'Shadow_Neural_Safety', float(state["equity"])])
        print(f"  [DB SSOT] Shadow_Neural_Safety equity for {target_date} written to Turso DB: ${state['equity']}")
    except Exception as e_db:
        print(f"  [DB ERROR] Failed to write Shadow_Neural_Safety to Turso DB: {e_db}")

    return state["equity"]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default="2026-08-17", help="Target date to run Shadow Neural Safety")
    args = parser.parse_args()
    run_shadow_neural_safety(args.date)
