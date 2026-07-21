import database_manager

print("PENDING:")
orders = database_manager.execute_query("SELECT * FROM pending_orders")
for o in orders:
    print(o)

print("\nLEDGERS:")
ledgers = database_manager.execute_query("SELECT * FROM capital_ledgers")
for l in ledgers:
    print(l)
