import os
import glob
import shutil

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
FINANCIAL_DIR = os.path.join(BASE_DIR, 'financial_data')
ARCHIVE_DIR = os.path.join(FINANCIAL_DIR, 'LEGACY_ARCHIVE_DO_NOT_USE')

if not os.path.exists(ARCHIVE_DIR):
    os.makedirs(ARCHIVE_DIR)

csv_files = glob.glob(os.path.join(FINANCIAL_DIR, "Capital_Ledger_*.csv")) + \
            glob.glob(os.path.join(FINANCIAL_DIR, "ETF_Capital_Ledger_*.csv"))

count = 0
for f in csv_files:
    filename = os.path.basename(f)
    dest = os.path.join(ARCHIVE_DIR, filename)
    shutil.move(f, dest)
    count += 1
    print(f"Archived: {filename}")

print(f"\nSuccessfully archived {count} legacy CSV ledgers. The system is now pure SSOT SQLite.")
