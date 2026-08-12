import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager

print("==================================================================")
print("                    ANTIGRAVITY SYSTEM STATUS REPORT              ")
print("==================================================================")

# 1. Process Continuity
try:
    print("\n--- Pipeline Status ---")
    df = database_manager.execute_query("SELECT * FROM process_continuity")
    for _, row in df.iterrows():
        print(f"  {row['pipeline_name']:<20}: Last Completed Date = {row['last_completed_date']}")
except Exception as e:
    print(f"Error querying process continuity: {e}")

# 2. Capital Ledgers (Yesterday's finalized balances)
yesterday = "2026-08-11"
try:
    print(f"\n--- Ledger Balances (Yesterday: {yesterday}) ---")
    df = database_manager.execute_query(f"SELECT persona, cash, total_equity FROM capital_ledgers WHERE date='{yesterday}'")
    if df.empty:
        print(f"  No ledger rows found for {yesterday}!")
    else:
        # Round columns for readability
        df['cash'] = df['cash'].round(2)
        df['total_equity'] = df['total_equity'].round(2)
        print(df.to_string(index=False))
except Exception as e:
    print(f"Error querying capital ledgers: {e}")

# 3. Today's Staged Pending Orders
try:
    print("\n--- Staged Pending Orders for Next Session ---")
    df = database_manager.execute_query("SELECT persona, date FROM pending_orders")
    if df.empty:
        print("  No pending orders staged!")
    else:
        print(df.to_string(index=False))
except Exception as e:
    print(f"Error querying pending orders: {e}")

sys.stdout.flush()
os._exit(0)
