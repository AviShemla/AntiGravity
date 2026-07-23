import sys
import os
import json
import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import database_manager

def get_report():
    print("=== YESTERDAY'S EXECUTIONS (2026-07-22) ===")
    df_yesterday = database_manager.execute_query("SELECT persona, intraday_status, daily_pnl_json FROM capital_ledgers WHERE date = '2026-07-22'")
    
    if df_yesterday.empty:
        print("No execution records found for yesterday.")
    else:
        for _, row in df_yesterday.iterrows():
            print(f"[{row['persona']}] Status: {row['intraday_status']} | PnL Details: {row['daily_pnl_json']}")
            
    print("\n=== NEW PENDING ORDERS FOR TODAY (2026-07-23) ===")
    df_today = database_manager.execute_query("SELECT persona, target_holdings_json FROM pending_orders")
    
    if df_today.empty:
        print("CRITICAL: No pending orders found for today!")
    else:
        for _, row in df_today.iterrows():
            target_date = "2026-07-23"
            holdings = json.loads(row['target_holdings_json']) if isinstance(row['target_holdings_json'], str) else row['target_holdings_json']
            tickers = list(holdings.keys())
            print(f"[{row['persona']}] Target Date: {target_date} | AI Recommendation: {len(tickers)} Tickers -> {', '.join(tickers)}")
            
    # Also verify if Vultr daemons are running for preflight sanity
    print("\n=== DAEMON SANITY CHECK ===")
    import psutil
    sniper_running = False
    for p in psutil.process_iter(['cmdline']):
        try:
            if p.info['cmdline'] and 'intraday_tracker.py' in " ".join(p.info['cmdline']).lower():
                sniper_running = True
                break
        except:
            pass
    print(f"Sniper Daemons Active (Vultr orchestrates this natively): {'Yes' if sniper_running else 'No (Local Check only)'}")

if __name__ == "__main__":
    get_report()
