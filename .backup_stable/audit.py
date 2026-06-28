import pandas as pd
import glob
import os

print("=== LEDGER AUDIT ===")
for f in glob.glob('financial_data/*Ledger*.csv'):
    try:
        df = pd.read_csv(f)
        latest_date = df["Date"].iloc[-1]
        print(f"{os.path.basename(f)}: {len(df)} rows, Latest Date: {latest_date}")
    except Exception as e:
        print(f"Error reading {f}: {e}")
