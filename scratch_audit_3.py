import database_manager
import pandas as pd
import json

print("\n--- EL_VOLTI Spike ---")
df = database_manager.execute_query("SELECT * FROM olympic_shootout_master WHERE model_name = 'EL_VOLTI (70% Stability)' AND date >= '2026-07-14' AND date <= '2026-07-18' ORDER BY date")
print(df)

print("\n--- Prod Drop Check in capital_ledgers ---")
df = database_manager.execute_query("SELECT * FROM capital_ledgers WHERE date >= '2026-07-22' AND date <= '2026-07-23' ORDER BY persona, date")
print(df[['persona', 'date', 'cash', 'total_equity']])

print("\n--- Double Entry Verification (Prod vs Shadow & Olympic) ---")
# To verify calculation integrity: starting_cash + sum(PnL) == total_equity across all personas (Stocks & ETFs).
# The prompt says: Mathematically prove that starting_cash + sum(PnL) == total_equity across all personas (Stocks & ETFs).
# And check for unverified equity jumps (>5% single-day delta)
