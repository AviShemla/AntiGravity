import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import database_manager

def get_live_status():
    print("=== LIVE TRADE DAY STATUS ===")
    
    # 1. Get Pending Orders
    df_pending = database_manager.execute_query("SELECT persona, executed_intraday_trades_json FROM pending_orders")
    
    pending_map = {}
    if not df_pending.empty:
        for _, row in df_pending.iterrows():
            try:
                # If there are executed trades mid-day before completion, they show up here
                executed = json.loads(row['executed_intraday_trades_json']) if isinstance(row['executed_intraday_trades_json'], str) else row['executed_intraday_trades_json']
                
                status_parts = []
                if executed:
                    if any(v.get('type') == 'BUY' for v in executed.values()): status_parts.append("BUY")
                    if any(v.get('type') == 'SELL' for v in executed.values()): status_parts.append("TP/SL")
                    if any(v.get('type') == 'ABORTED_SELL' for v in executed.values()): status_parts.append("ABORTED SELL")
                    
                pending_map[row['persona']] = "Tracking VWAP" if not status_parts else f"Tracking VWAP (Exec: {' & '.join(status_parts)})"
            except:
                pending_map[row['persona']] = "Tracking VWAP"

    # 2. Get Today's Ledger Entries (for completed personas or live PNL)
    df_ledgers = database_manager.execute_query("SELECT persona, date, total_equity, daily_pnl_json, intraday_status FROM capital_ledgers WHERE date = '2026-07-22'")
    
    ledger_map = {}
    if not df_ledgers.empty:
        for _, row in df_ledgers.iterrows():
            try:
                pnl = json.loads(row['daily_pnl_json']) if isinstance(row['daily_pnl_json'], str) else row['daily_pnl_json']
                total_pnl = sum(pnl.values()) if isinstance(pnl, dict) else 0.0
                ledger_map[row['persona']] = {
                    "status": row['intraday_status'] if row['intraday_status'] else "COMPLETED",
                    "pnl": total_pnl
                }
            except:
                ledger_map[row['persona']] = {"status": "COMPLETED", "pnl": 0.0}

    # All personas
    personas = [
        "Conservative", "Neutral", "Dynamic", "BallsForBrains",
        "ETF_Conservative", "ETF_Neutral", "ETF_Dynamic", "ETF_BallsForBrains"
    ]
    
    print("Persona | Status | PnL")
    for p in personas:
        if p in ledger_map:
            status = ledger_map[p]["status"]
            pnl = ledger_map[p]["pnl"]
        elif p in pending_map:
            status = pending_map[p]
            pnl = "Live tracking..."
        else:
            status = "No data found for today"
            pnl = "N/A"
            
        print(f"{p} | {status} | {pnl}")

if __name__ == "__main__":
    get_live_status()
