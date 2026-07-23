import sys
import os

# Add AntiGravity to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import database_manager

def verify():
    print("=== TURSO DATABASE QA ===")
    try:
        # Check Capital Ledgers
        res = database_manager.execute_query("SELECT COUNT(*) as count FROM capital_ledgers")
        print(f"Capital Ledgers count: {res['count'].iloc[0] if not res.empty else 0}")
        
        # Check Pending Orders Schema
        res_schema = database_manager.execute_query("PRAGMA table_info(pending_orders)")
        columns = res_schema['name'].tolist() if not res_schema.empty else []
        print(f"Pending Orders Schema: {columns}")
        
        if 'ticker' in columns:
            res_orders = database_manager.execute_query("SELECT persona, ticker, date FROM pending_orders")
        elif 'asset_id' in columns:
            res_orders = database_manager.execute_query("SELECT persona, asset_id, date FROM pending_orders")
        else:
            res_orders = database_manager.execute_query("SELECT * FROM pending_orders LIMIT 10")
            
        print(f"Pending Orders count: {len(res_orders)}")
        if len(res_orders) > 0:
            print("Latest Pending Orders sample:")
            print(res_orders.head())
        else:
            print("No pending orders currently found.")
            
        print("TURSO QA PASSED.")
    except Exception as e:
        print(f"TURSO QA FAILED: {e}")

if __name__ == "__main__":
    verify()
