import pandas as pd
import os
import glob

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
ledgers = glob.glob(os.path.join(BASE_DIR, '*Capital_Ledger_*.csv'))

for ledger_path in ledgers:
    df = pd.read_csv(ledger_path)
    if not df.empty and str(df['Date'].iloc[-1]).startswith('2026-06-10'):
        df = df.iloc[:-1] # Drop the last row
        df.to_csv(ledger_path, index=False)
        print(f"Reverted {os.path.basename(ledger_path)} to June 9th.")
