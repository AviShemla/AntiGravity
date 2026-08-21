import database_manager
import json
import pandas as pd

print("--- PnL Verification ---")
df = database_manager.execute_query("SELECT * FROM capital_ledgers ORDER BY persona, date")

anomalies = []
for persona in df['persona'].unique():
    persona_df = df[df['persona'] == persona].sort_values('date')
    starting_cash = 10000.0 # assuming 10k initial
    cumulative_pnl = 0.0
    
    for _, row in persona_df.iterrows():
        try:
            pnl_data = json.loads(row['daily_pnl_json'])
            daily_pnl = pnl_data.get('total_pnl', 0.0) if isinstance(pnl_data, dict) else 0.0
        except:
            daily_pnl = 0.0
        
        cumulative_pnl += daily_pnl
        expected_equity = starting_cash + cumulative_pnl
        actual_equity = row['total_equity']
        
        if abs(expected_equity - actual_equity) > 0.5:
            # We flag an anomaly if the math doesn't check out.
            # However, note that some days might just lack PnL. Let's see if this mismatch occurs.
            anomalies.append({
                'persona': persona,
                'date': row['date'],
                'expected': expected_equity,
                'actual': actual_equity,
                'diff': actual_equity - expected_equity
            })

if anomalies:
    print(f"Found {len(anomalies)} anomalies where 10000 + sum(PnL) != equity")
    print(pd.DataFrame(anomalies).head(20))
else:
    print("All equity values match 10000 + sum(PnL)")

print("\n--- Spikes / Drops Investigation ---")
print("1. Prod Drop on 07-23")
prod_df = database_manager.execute_query("SELECT * FROM capital_ledgers WHERE persona = 'BallsForBrains' AND date IN ('2026-07-22', '2026-07-23')")
for _, row in prod_df.iterrows():
    print(row['date'], row['total_equity'], row['daily_pnl_json'])

print("\n2. Shadow Transformer Drop on 08-04 to 08-05")
# Doesn't exist in capital_ledgers. Only in prod_vs_shadow_master. Let's see if it's derived from somewhere.
df_ps = database_manager.execute_query("SELECT * FROM prod_vs_shadow_master WHERE model_name = 'Shadow_Transformer' AND date >= '2026-08-03' AND date <= '2026-08-06'")
print(df_ps)

print("\n3. EL_VOLTI Spike on 07-16")
df_ol = database_manager.execute_query("SELECT * FROM olympic_shootout_master WHERE model_name = 'EL_VOLTI (70% Stability)' AND date >= '2026-07-15' AND date <= '2026-07-17'")
print(df_ol)

