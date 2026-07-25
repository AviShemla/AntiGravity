import os
import sys
import json
import pandas as pd
import database_manager as dbm

# Query the Turso database to check the intraday status for all personas
pending_df = dbm.execute_query("SELECT persona, date, target_holdings_json, executed_intraday_trades_json, daily_pnl_json FROM pending_orders")

ledgers_df = dbm.execute_query("SELECT persona, date, intraday_status, daily_pnl_json, holdings_json FROM capital_ledgers WHERE date = '2026-07-23'")

print("---PENDING---")
if not pending_df.empty:
    print(pending_df.to_json(orient='records'))
else:
    print("[]")

print("---LEDGERS---")
if not ledgers_df.empty:
    print(ledgers_df.to_json(orient='records'))
else:
    print("[]")
