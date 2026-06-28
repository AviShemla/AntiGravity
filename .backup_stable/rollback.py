import pandas as pd
import glob
import os

print("=== ROLLING BACK SINGLE STOCK LEDGERS ===")
for f in glob.glob('financial_data/Capital_Ledger_*.csv'):
    try:
        df = pd.read_csv(f)
        # Keep only rows on or before 2026-05-28
        df_clean = df[df['Date'] <= '2026-05-28']
        df_clean.to_csv(f, index=False)
        print(f"Rolled back {os.path.basename(f)} to {df_clean['Date'].iloc[-1]} ({len(df_clean)} rows)")
    except Exception as e:
        print(f"Error rolling back {f}: {e}")
