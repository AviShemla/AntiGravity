import database_manager
import pandas as pd

ledger = database_manager.get_ledger("Neutral")
print("Neutral Ledger Dates:")
print(ledger['Date'].tolist() if not ledger.empty else "Empty Ledger")

if not ledger.empty:
    target_rows = ledger[ledger['Date'] == '2026-06-12']
    print("\nRows for 2026-06-12:")
    print(target_rows)
