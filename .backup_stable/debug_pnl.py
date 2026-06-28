import pandas as pd
import json

df = pd.read_excel('financial_data/Top5_Bayesian_Scorecard_Formatted.xlsx', sheet_name='MU', skiprows=2)
target_date_for_ledger = '2026-05-29'
df = df[df['date'] <= pd.to_datetime(target_date_for_ledger)]

settlement_row = df.iloc[-2]
pending_row = df.iloc[-1]

holdings = {"MU": {"dollars": 1856.82, "units": 2, "price": 928.41}, "FAKEZOMBIE": {"dollars": 500.0, "units": 10, "price": 50.0}}

daily_pnl = {}
settled_equity = 0.0

if 'MU' in holdings:
    item = holdings['MU']
    allocated_dollars = item.get("dollars", 0.0)
    actual_return_pct = settlement_row['actual value daily return %']
    
    if pd.notna(actual_return_pct):
        pnl = allocated_dollars * actual_return_pct
        daily_pnl['MU'] = pnl
        settled_equity += (allocated_dollars + pnl)
    else:
        daily_pnl['MU'] = 0.0
        settled_equity += allocated_dollars

print(f"Settlement Row Date: {settlement_row['date']}")
print(f"Actual Return PCT: {actual_return_pct}")
print(f"Daily PnL: {daily_pnl}")
print(f"Daily_PnL_JSON: {json.dumps({k: round(v, 2) for k, v in daily_pnl.items()})}")
