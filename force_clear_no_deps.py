import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'antigravity.db')

def force_clear():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
        c.execute('''
            INSERT INTO capital_ledgers (persona, date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status, engine_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (persona, date_str, cash, total_equity, holdings, '{}', "EOD_FORCED", "V1.0 - Pure PyMC Bayesian"))
    
    # Clear pending orders
    c.execute('DELETE FROM pending_orders')
    conn.commit()
    conn.close()
    
    print("All pending orders cleared and pushed to ledger!")

if __name__ == "__main__":
    force_clear()
