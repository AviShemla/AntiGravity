import database_manager
import pandas as pd

print("--- Checking for 2026-07-25 ---")
df_p = database_manager.execute_query("SELECT * FROM prod_vs_shadow_master WHERE date = '2026-07-25'")
print("prod_vs_shadow_master:", df_p)
df_o = database_manager.execute_query("SELECT * FROM olympic_shootout_master WHERE date = '2026-07-25'")
print("olympic_shootout_master:", df_o)

print("\n--- Checking weekends ---")
df_all_p = database_manager.execute_query("SELECT DISTINCT date FROM prod_vs_shadow_master")
df_all_o = database_manager.execute_query("SELECT DISTINCT date FROM olympic_shootout_master")

def get_weekends(df):
    if df.empty: return []
    df['date_pd'] = pd.to_datetime(df['date'])
    weekends = df[df['date_pd'].dt.dayofweek >= 5]
    return weekends['date'].tolist()

weekends_p = get_weekends(df_all_p)
weekends_o = get_weekends(df_all_o)
print(f"prod_vs_shadow_master weekends count: {len(weekends_p)}")
print(f"olympic_shootout_master weekends count: {len(weekends_o)}")

print("\n--- Checking Spikes/Drops ---")
print("EL_VOLTI (07-14 to 07-18):")
df = database_manager.execute_query("SELECT * FROM olympic_shootout_master WHERE model_name = 'EL_VOLTI' AND date >= '2026-07-14' AND date <= '2026-07-18' ORDER BY date")
print(df)

print("\nShadow Transformer (08-01 to 08-06):")
df = database_manager.execute_query("SELECT * FROM prod_vs_shadow_master WHERE model_name = 'Shadow_Transformer' AND date >= '2026-08-01' AND date <= '2026-08-06' ORDER BY date")
print(df)

print("\nProd (07-20 to 07-25):")
df = database_manager.execute_query("SELECT * FROM prod_vs_shadow_master WHERE model_name = 'Prod' AND date >= '2026-07-20' AND date <= '2026-07-25' ORDER BY date")
print(df)

df_cl = database_manager.execute_query("SELECT * FROM capital_ledgers WHERE persona = 'Prod' AND date >= '2026-07-20' AND date <= '2026-07-25' ORDER BY date")
print("\nProd (capital_ledgers 07-20 to 07-25):")
if not df_cl.empty:
    print(df_cl[['date', 'cash', 'total_equity', 'holdings_json']])
else:
    print("Empty")

