import sys, os
sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
import database_manager as dbm

with open('scratch_out.txt', 'w') as f:
    try:
        f.write("--- Pending Orders by Persona ---\n")
        orders = dbm.execute_query('SELECT persona, COUNT(*) as count FROM pending_orders GROUP BY persona')
        f.write(orders.to_string() + "\n")
        
        f.write("\n--- Capital Ledgers on 2026-07-20 ---\n")
        ledgers = dbm.execute_query("SELECT persona FROM capital_ledgers WHERE date = '2026-07-20'")
        f.write(ledgers.to_string() + "\n")
        
    except Exception as e:
        f.write(f"Error: {e}\n")

os._exit(0)
