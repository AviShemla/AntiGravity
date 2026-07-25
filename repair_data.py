import pandas as pd
import json
import os

base_dir = r"C:\Users\AviShemla\AntiGravity\financial_data"
csv_path = os.path.join(base_dir, "Prod_vs_Shadow_Results_MASTER.csv")
json_path = os.path.join(base_dir, "prod_shadow_state.json")

# 1. Repair CSV
if os.path.exists(csv_path):
    df = pd.read_csv(csv_path)
    # Remove the corrupted 2026-07-24 row
    df = df[df['Date'] != '2026-07-24']
    df.to_csv(csv_path, index=False)
    print("Repaired CSV: Dropped 2026-07-24.")

# 2. Repair JSON state
if os.path.exists(json_path):
    with open(json_path, 'r') as f:
        state = json.load(f)
    
    # We must revert the equity states to the last valid values from the CSV for 2026-07-23
    # From previous lookup, 2026-07-23 values were: 
    # Trans: 9690.07, V1: 11705.49, LSTM: 10173.94
    state['Transformer'] = 9690.07
    state['V1_Classic'] = 11705.49
    state['LSTM_Shadow'] = 10173.94
    state['last_date'] = '2026-07-23'
    
    with open(json_path, 'w') as f:
        json.dump(state, f)
    print("Repaired JSON state: Reverted to 2026-07-23 values.")
