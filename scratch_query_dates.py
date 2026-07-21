import sys, os
sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
import database_manager as dbm

with open('scratch_out_dates.txt', 'w') as f:
    try:
        f.write("--- Pending Orders Dates ---\n")
        orders = dbm.execute_query('SELECT persona, date FROM pending_orders')
        f.write(orders.to_string() + "\n")
    except Exception as e:
        f.write(f"Error: {e}\n")

os._exit(0)
