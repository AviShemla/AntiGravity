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
STATE_JSON = os.path.join(BASE_DIR, "financial_data", "shadow_etf_whale_state.json")

# Core Sector ETFs
ETF_SECTORS = ['XLK', 'XLF', 'XLV', 'XLE', 'XLY', 'XLP', 'XLU', 'XLI', 'XLB', 'XLC', 'XLRE']

# Fundamental Sector Weight Priors (Derived from S&P 500 GICS Balance Sheet Aggregates)
SECTOR_FUNDAMENTAL_PRIORS = {
    'XLK': 1.15, # Technology - High FCF Yield
    'XLV': 1.10, # Healthcare - Strong Balance Sheet / Cash Reserves
    'XLC': 1.05, # Communication - Solid Profitability
    'XLF': 1.00, # Financials - Baseline
    'XLI': 0.98, # Industrials - Baseline
    'XLY': 0.95, # Consumer Discretionary - Moderated Demand
    'XLP': 0.95, # Consumer Staples - High Valuation
    'XLE': 1.08, # Energy - Strong Free Cash Flow
    'XLB': 0.90, # Materials - Cyclical Pressure
    'XLU': 0.92, # Utilities - High Debt/Leverage
    'XLRE': 0.88 # Real Estate - Interest Rate Headwinds
}

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

def run_shadow_etf_whale(target_date):
    print(f"\n--- [SHADOW CONTENDER #1] Running Shadow ETF Whale Engine for {target_date} ---")
    state = load_state()
    
    # 1. Fetch 5d returns for Sector ETFs
    etf_returns = {}
    for etf in ETF_SECTORS:
        try:
            df = download_ticker_with_failover(etf, period="5d")
            if df is not None and not df.empty:
                df = df.ffill()
                if target_date in df.index.strftime('%Y-%m-%d'):
                    idx = list(df.index.strftime('%Y-%m-%d')).index(target_date)
                    if idx > 0:
                        prev_close = float(df['Close'].iloc[idx-1])
                        curr_close = float(df['Close'].iloc[idx])
                        ret = (curr_close - prev_close) / prev_close
                        etf_returns[etf] = (ret, curr_close)
        except Exception as e:
            print(f"  [WARNING] Failed to fetch {etf} return: {e}")

    # 2. Mark-to-Market Existing Portfolio
    curr_equity = state["equity"]
    if state["holdings"]:
        mtm_equity = state.get("cash", curr_equity)
        for etf, h_data in state["holdings"].items():
            if etf in etf_returns:
                units = float(h_data.get("units", 0))
                price = etf_returns[etf][1]
                mtm_equity += units * price
        curr_equity = mtm_equity

    # 3. Apply Fundamental Whale Prior Allocation (Task #1 Logic)
    # Compute Bayesian-Weighted Sector Scores
    raw_scores = {}
    for etf in ETF_SECTORS:
        prior = SECTOR_FUNDAMENTAL_PRIORS.get(etf, 1.00)
        ret, price = etf_returns.get(etf, (0.0, 100.0))
        # Likelihood signal boosted by Fundamental Prior
        score = prior * (1.0 + ret)
        raw_scores[etf] = score
        
    # Select Top 3 Fundamental-Weighted ETFs
    sorted_etfs = sorted(raw_scores.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Target Allocation: 25% cash reserve, 75% split across top 3 fundamental sector ETFs
    alloc_capital = curr_equity * 0.75
    per_etf_alloc = alloc_capital / len(sorted_etfs)
    
    new_holdings = {}
    remaining_cash = curr_equity - alloc_capital
    for etf, score in sorted_etfs:
        if etf in etf_returns:
            price = etf_returns[etf][1]
            units = int(per_etf_alloc // price)
            actual_dollars = units * price
            remaining_cash += (per_etf_alloc - actual_dollars)
            new_holdings[etf] = {
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

    # 4. Write directly to Turso DB SSOT (prod_vs_shadow_master)
    try:
        database_manager.execute_write("""
            INSERT INTO prod_vs_shadow_master (date, model_name, total_equity)
            VALUES (?, ?, ?)
            ON CONFLICT(date, model_name) DO UPDATE SET total_equity=excluded.total_equity
        """, [target_date, 'Shadow_ETF_Whale', float(state["equity"])])
        print(f"  [DB SSOT] Shadow_ETF_Whale equity for {target_date} written to Turso DB: ${state['equity']}")
    except Exception as e_db:
        print(f"  [DB ERROR] Failed to write Shadow_ETF_Whale to Turso DB: {e_db}")

    return state["equity"]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default="2026-08-17", help="Target date to run Shadow ETF Whale")
    args = parser.parse_args()
    run_shadow_etf_whale(args.date)
