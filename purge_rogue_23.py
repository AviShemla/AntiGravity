import os
import json
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "financial_data")
MASTER_CSV = os.path.join(DATA_DIR, "Prod_vs_Shadow_Results_MASTER.csv")
STATE_JSON = os.path.join(DATA_DIR, "prod_shadow_state.json")

# 1. Purge the rogue 23rd from CSV
if os.path.exists(MASTER_CSV):
    df = pd.read_csv(MASTER_CSV)
    if 'Date' in df.columns:
        df = df[df['Date'] != '2026-07-23']
        df.to_csv(MASTER_CSV, index=False)
        print("Purged rogue 2026-07-23 from CSV.")

# 2. Revert the state JSON
if os.path.exists(STATE_JSON):
    with open(STATE_JSON, 'r') as f:
        st = json.load(f)
    if st.get('last_date') == '2026-07-23':
        st['last_date'] = '2026-07-22'
        with open(STATE_JSON, 'w') as f:
            json.dump(st, f)
        print("Reverted state last_date to 2026-07-22.")
