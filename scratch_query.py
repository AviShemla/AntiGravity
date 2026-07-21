import sys
sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
import database_manager as dbm

try:
    print("Checking pending_orders...")
    res = dbm.execute_query('SELECT COUNT(*) FROM pending_orders')
    print("Pending orders count:")
    print(res)
    
    print("\nChecking capital_ledgers...")
    ledgers = dbm.execute_query('SELECT date, COUNT(*) FROM capital_ledgers GROUP BY date ORDER BY date DESC LIMIT 5')
    print("Recent capital_ledgers entries:")
    print(ledgers)
    
except Exception as e:
    print(f"Error: {e}")
