import database_manager as dbm
print(dbm.execute_query("SELECT * FROM pending_orders WHERE persona='Conservative'").to_string())
