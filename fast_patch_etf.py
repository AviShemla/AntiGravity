import os
import sys
import pandas as pd
import json
import sqlite3
import etf_virtual_broker
import database_manager

def patched_get_ledger(persona):
    conn = sqlite3.connect("C:/Users/AviShemla/AntiGravity/financial_data/ag_pipeline_fallback.db")
    df = pd.read_sql_query(f"SELECT * FROM capital_ledgers WHERE persona='{persona}'", conn)
    conn.close()
    return df

def patched_save(persona, **kwargs):
    path = "C:/Users/AviShemla/AntiGravity/financial_data/Pending_Orders.json"
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except:
        data = {}
    
    # map kwargs exactly as needed
    date = kwargs.get('date', kwargs.get('target_date', ''))
    cash = kwargs.get('target_cash', 0.0)
    eq = kwargs.get('target_total_equity', 0.0)
    hold = kwargs.get('target_holdings', {})
    pnl = kwargs.get('daily_pnl', {})
    trades = kwargs.get('executed_trades', {})

    data[persona] = {
        "Persona": persona,
        "Date": date,
        "Target_Cash": cash,
        "Target_Total_Equity": eq,
        "Target_Holdings": hold,
        "Daily_PnL_JSON": pnl,
        "Executed_Intraday_Trades": trades
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
        
    print(f"Patched saving for {persona} complete.")

database_manager.get_ledger = patched_get_ledger
database_manager.save_pending_order = patched_save

etf_virtual_broker.target_date_for_ledger = "2026-07-22"
try:
    print("Starting patched ETF virtual broker run...")
    etf_virtual_broker.run_etf_virtual_broker()
    print("PATCHED AND SAVED PENDING ORDERS JSON LOCALLY!")
except Exception as e:
    import traceback
    traceback.print_exc()

import sys; sys.stdout.flush(); os._exit(0)
