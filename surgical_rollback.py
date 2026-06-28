import pandas as pd
import glob
import os

print("=== EXECUTING SURGICAL ETF ROLLBACK ===")
base_dir = r'C:\Users\AviShemla\AntiGravity\financial_data'

# 1. Strip 2026-06-04 rows from ETF Ledgers
for f in glob.glob(os.path.join(base_dir, 'ETF_Capital_Ledger_*.csv')):
    try:
        df = pd.read_csv(f)
        # We want to remove the phantom '2026-06-04' trades
        df_clean = df[df['Date'] < '2026-06-04']
        df_clean.to_csv(f, index=False)
        print(f"[CLEARED] {os.path.basename(f)} successfully reverted to {df_clean['Date'].iloc[-1]} ({len(df_clean)} rows)")
    except Exception as e:
        print(f"[ERROR] Failed to roll back {os.path.basename(f)}: {e}")

# 2. Wipe corrupted Scorecards and Matrices
targets = [
    os.path.join(base_dir, 'All_ETFs_Scorecard.xlsx')
]
targets.extend(glob.glob(os.path.join(base_dir, '*_Hybrid_Matrix.csv')))
targets.extend(glob.glob(os.path.join(base_dir, '*_Hybrid_Screener_Results.csv')))

for target in targets:
    if os.path.exists(target):
        try:
            mtime = os.path.getmtime(target)
            import datetime
            dt = datetime.datetime.fromtimestamp(mtime)
            # Only delete if generated on June 4th
            if dt.day == 4 and dt.month == 6 and dt.year == 2026:
                os.remove(target)
                print(f"[WIPED] Ghost file deleted: {os.path.basename(target)}")
        except Exception as e:
            print(f"[WARNING] Could not delete {os.path.basename(target)}: {e}")

print("=== ROLLBACK COMPLETE ===")
