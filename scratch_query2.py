import sys, os
sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
import database_manager as dbm

try:
    print("--- Pending Orders by Persona ---")
    orders = dbm.execute_query('SELECT persona, COUNT(*) FROM pending_orders GROUP BY persona')
    print(orders)
    
    print("\n--- Capital Ledgers on 2026-07-20 ---")
    ledgers = dbm.execute_query("SELECT persona FROM capital_ledgers WHERE date = '2026-07-20'")
    print(ledgers)
    
except Exception as e:
    print(f"Error: {e}")

os._exit(0)
