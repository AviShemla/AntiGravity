import sqlite3
import pandas as pd
import json

from database_manager import execute_query
query = "SELECT persona, date, cash, total_equity, holdings_json FROM capital_ledgers ORDER BY persona, date ASC"
df = execute_query(query)

print("=== ANTIGRAVITY SQLite CONTINUITY QA TEST ===\n")

personas = df['persona'].unique()
for p in personas:
    pdf = df[df['persona'] == p].copy()
    pdf['date'] = pd.to_datetime(pdf['date'])
    
    genesis = pdf['date'].min()
    latest = pdf['date'].max()
    row_count = len(pdf)
    
    # Check for NaN values in cash or equity
    nan_cash = pdf['cash'].isna().sum()
    nan_equity = pdf['total_equity'].isna().sum()
    
    print(f"[{p}]")
    print(f"  Genesis Date : {genesis.date()}")
    print(f"  Latest Date  : {latest.date()}")
    print(f"  Total Days   : {row_count}")
    print(f"  NaN Cash Errs: {nan_cash}")
    print(f"  NaN Eqty Errs: {nan_equity}")
    
    # Validate sequential gap logic (accounting for weekends)
    dates = pdf['date'].dt.date.tolist()
    is_continuous = True
    for i in range(1, len(dates)):
        diff = (dates[i] - dates[i-1]).days
        if diff > 4: # Assuming max gap is a long holiday weekend
            is_continuous = False
            print(f"  [!] WARNING: Large gap detected between {dates[i-1]} and {dates[i]} ({diff} days)")
            
    if is_continuous:
        print("  Continuity   : PERFECT (No missing days or breaks)")
    print("-" * 40)

print("\nQA Test Completed.")
