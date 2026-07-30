import os
import sys
import pandas as pd
import json

sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
import database_manager

def heal_missing_date(persona, missing_date, source_date):
    print(f"Healing {persona} for {missing_date} using {source_date}...")
    df = database_manager.execute_query(f"SELECT * FROM capital_ledgers WHERE persona='{persona}' AND date='{source_date}'")
    if df.empty:
        print(f"Source date {source_date} not found for {persona}!")
        return

    row = df.iloc[0]
    
    # Save ledger row for the missing date
    database_manager.save_ledger_row(
        persona=persona,
        date=missing_date,
        cash=float(row['cash']),
        total_equity=float(row['total_equity']),
        holdings_json=row['holdings_json'],
        daily_pnl_json=row['daily_pnl_json'],
        intraday_status=row['intraday_status']
    )
    print(f"Successfully healed {persona} on {missing_date}")

heal_missing_date('Neutral', '2026-07-22', '2026-07-21')
heal_missing_date('ETF_Neutral', '2026-07-22', '2026-07-21')
