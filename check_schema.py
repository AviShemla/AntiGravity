import database_manager

res = database_manager.execute_query("PRAGMA table_info(pending_orders);")
with open("schema_dump.txt", "w") as f:
    for r in res:
        f.write(str(r) + "\n")
