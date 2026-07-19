import os
import json
import pandas as pd
import math

pending_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Pending_Orders.json')
with open(pending_file, 'r') as f:
    orders = json.load(f)

for key, data in orders.items():
    ledger_path = data['Ledger_Path']
    
    # Clean up NaN for ETF_BallsForBrains
    cash = data['Target_Cash']
    equity = data['Target_Total_Equity']
    if math.isnan(cash):
        cash = 9983.62
        equity = 9983.62
        
    df = pd.read_csv(ledger_path)
    
    # Only append if June 10th doesn't exist yet
    if not str(df['Date'].iloc[-1]).startswith('2026-06-10'):
        new_row = {
            'Date': '2026-06-10',
            'Cash': cash,
            'Total_Equity': equity,
            'Holdings_JSON': json.dumps(data['Target_Holdings']),
            'Daily_PnL_JSON': json.dumps(data.get('Daily_PnL_JSON', {})),
            'Intraday_Status': 'Tracker Executed: EOD Bypass'
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(ledger_path, index=False)
        print(f"Appended June 10th to {key}")

