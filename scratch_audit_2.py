import database_manager
import pandas as pd
import json

print("\n--- Olympic Shootout EL_VOLTI ---")
df = database_manager.execute_query("SELECT * FROM olympic_shootout_master WHERE model_name LIKE '%VOLTI%' ORDER BY date")
print(df.head(10))
print(df.tail(10))

print("\n--- Prod Persona Check ---")
df = database_manager.execute_query("SELECT DISTINCT persona FROM capital_ledgers")
print(df)
df = database_manager.execute_query("SELECT * FROM capital_ledgers WHERE persona LIKE '%Prod%' AND date >= '2026-07-20' AND date <= '2026-07-25' ORDER BY date")
print(df[['date', 'cash', 'total_equity']])

print("\n--- Missing 08-04 ---")
df = database_manager.execute_query("SELECT DISTINCT date FROM prod_vs_shadow_master WHERE date >= '2026-08-01' ORDER BY date")
print(df)
