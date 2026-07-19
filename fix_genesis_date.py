import pandas as pd
import os
import glob

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
ledgers = glob.glob(os.path.join(BASE_DIR, '*Capital_Ledger_*.csv'))

for ledger_path in ledgers:
    df = pd.read_csv(ledger_path)
    if not df.empty and str(df['Date'].iloc[0]).startswith('2025-05'):
        # Fix the genesis date to 2026-04-22 (one day before trading begins)
        df.at[0, 'Date'] = '2026-04-22'
        df.to_csv(ledger_path, index=False)
        print(f"Fixed Genesis Date in {os.path.basename(ledger_path)}")
