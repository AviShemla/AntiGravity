import database_manager

print("Querying Turso DB for 13787...")
df1 = database_manager.execute_query("SELECT * FROM prod_vs_shadow_master WHERE total_equity > 13000")
print("prod_vs_shadow_master:")
print(df1)

df2 = database_manager.execute_query("SELECT * FROM olympic_shootout_master WHERE total_equity > 13000")
print("olympic_shootout_master:")
print(df2)
