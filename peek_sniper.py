import os
import sys
import json
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import database_manager
from intraday_tracker import get_yesterday_metrics, get_live_metrics, get_vix_score

def peek():
    print("=== SNIPER LIVE RADAR (READ-ONLY) ===")
    vix = get_vix_score()
    print(f"Live VIX Score: {vix}\n")
    
    df_pending = database_manager.execute_query("SELECT persona, target_holdings_json FROM pending_orders LIMIT 1")
    if df_pending.empty:
        print("No pending orders found.")
        return
        
    row = df_pending.iloc[0]
    persona = row['persona']
    target = json.loads(row['target_holdings_json']) if isinstance(row['target_holdings_json'], str) else row['target_holdings_json']
    
    # Just check the first 3 tickers to show the user what the Sniper is seeing
    tickers = list(target.keys())[:3]
    
    for ticker in tickers:
        print(f"Stalking: {ticker} (Persona: {persona})")
        yest_close, yest_vwap = get_yesterday_metrics(ticker)
        live_price, live_volume = get_live_metrics(ticker)
        
        if not yest_close or not live_price:
            print("  -> Waiting on data...")
            continue
            
        dynamic_vwap_threshold = yest_vwap * 1.005
        
        print(f"  -> Yesterday Close: ${yest_close:.2f}")
        print(f"  -> Yesterday VWAP : ${yest_vwap:.2f}")
        print(f"  -> Target Breakout: ${dynamic_vwap_threshold:.2f}")
        print(f"  -> Live Ask Price : ${live_price:.2f}")
        
        if (live_price > yest_close) and (live_price > dynamic_vwap_threshold):
            print("  -> STATUS: MOMENTUM PASSED. Awaiting Volume Confirmation.")
        else:
            print("  -> STATUS: MOMENTUM FAILED. Holding fire.")
        print("-" * 40)
        time.sleep(1)

if __name__ == "__main__":
    peek()
