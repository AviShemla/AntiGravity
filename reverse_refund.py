import pandas as pd
import json
import os
import glob

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
ledgers = glob.glob(os.path.join(BASE_DIR, '*Capital_Ledger_*.csv'))

print('=== REVERSING HISTORICAL REFUNDS ===\n')

for ledger_path in ledgers:
    df = pd.read_csv(ledger_path)
    if df.empty: continue
    
    historical_incorrect_refund = 0.0
    previous_holdings = {}
    
    for idx, row in df.iterrows():
        # We only want to reverse refunds that were NOT on the last day (June 10th)
        if str(row['Date']) == '2026-06-10':
            continue
            
        try:
            current_holdings = json.loads(row['Holdings_JSON'])
        except:
            current_holdings = {}
            
        for ticker, data in current_holdings.items():
            if isinstance(data, dict):
                units = data.get('units', -1)
                dollars = data.get('dollars', 0.0)
                
                if units == 0 and dollars > 0:
                    prev_data = previous_holdings.get(ticker, {})
                    prev_units = prev_data.get('units', -1) if isinstance(prev_data, dict) else -1
                    
                    if prev_units != 0:
                        historical_incorrect_refund += dollars
                        
        previous_holdings = current_holdings
        
    if historical_incorrect_refund > 0:
        print(f"[{os.path.basename(ledger_path)}] Reversing incorrect historical refund: -")
        
        # Apply the reversal to the FINAL row
        final_cash = float(df.iloc[-1]['Cash'])
        final_equity = float(df.iloc[-1]['Total_Equity'])
        
        df.at[df.index[-1], 'Cash'] = round(final_cash - historical_incorrect_refund, 2)
        df.at[df.index[-1], 'Total_Equity'] = round(final_equity - historical_incorrect_refund, 2)
        
        df.to_csv(ledger_path, index=False)
        print(f"-> Successfully reversed! New Final Cash: ")

print('\nNow regenerating the Excel Broker Trial files with the corrected ledgers...')
