import os
import json
import pandas as pd
import subprocess

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
DATA_DIR = os.path.join(BASE_DIR, "financial_data")
CSV_PATH = os.path.join(DATA_DIR, "Prod_vs_Shadow_Results_MASTER.csv")
STATE_PATH = os.path.join(DATA_DIR, "prod_shadow_state.json")

# 1. Truncate CSV to July 13
df = pd.read_csv(CSV_PATH)
df['Date'] = pd.to_datetime(df['Date'])
df = df[df['Date'] <= pd.Timestamp('2026-07-13')]
df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
df.to_csv(CSV_PATH, index=False)

# 2. Reset State to July 13
state = {
    'Transformer': 10856.76, 
    'V1_Classic': 10983.24, 
    'LSTM_Shadow': 10987.68, 
    'last_date': '2026-07-13', 
    'holdings_transformer': 'NKE', 
    'holdings_v1': 'LYB', 
    'holdings_lstm': 'MCD'
}
with open(STATE_PATH, 'w') as f:
    json.dump(state, f)

# 3. Re-run sequentially
print("Running 14th...")
subprocess.run(["C:\\Users\\AviShemla\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe", "prod_vs_shadow_tracker.py", "2026-07-14"], cwd=BASE_DIR)
print("Running 15th...")
subprocess.run(["C:\\Users\\AviShemla\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe", "prod_vs_shadow_tracker.py", "2026-07-15"], cwd=BASE_DIR)
print("Running 16th...")
subprocess.run(["C:\\Users\\AviShemla\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe", "prod_vs_shadow_tracker.py", "2026-07-16"], cwd=BASE_DIR)
print("Done!")
