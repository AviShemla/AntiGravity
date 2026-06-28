import sys
sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
import database_manager
import sqlite3
import json

def force_clear():
    conn = database_manager.get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM pending_orders')
    orders = c.fetchall()
    
    for order in orders:
        persona = order['persona']
        date_str = order['date']
        cash = order['target_cash']
        total_equity = order['target_total_equity']
        holdings = order['target_holdings_json']
        
        print(f"Force clearing {persona} for {date_str}...")
        database_manager.save_ledger_row(
            persona=persona,
            date=date_str,
            cash=cash,
            total_equity=total_equity,
            holdings_json=holdings,
            daily_pnl_json='{}',  # Day 0 of trades has 0 PnL
            intraday_status="EOD_FORCED",
            engine_version="V1.0 - Pure PyMC Bayesian"
        )
    
    # Clear pending orders
    c.execute('DELETE FROM pending_orders')
    conn.commit()
    conn.close()
    
    print("All pending orders cleared and pushed to ledger!")

if __name__ == "__main__":
    force_clear()
