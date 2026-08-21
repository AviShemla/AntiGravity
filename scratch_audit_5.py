import database_manager

print("--- Check all VOLTI models ---")
df = database_manager.execute_query("SELECT DISTINCT model_name FROM olympic_shootout_master WHERE model_name LIKE '%VOLTI%'")
print(df)

df = database_manager.execute_query("SELECT * FROM olympic_shootout_master WHERE model_name LIKE '%VOLTI%' AND date >= '2026-07-14' AND date <= '2026-07-18'")
print(df)
