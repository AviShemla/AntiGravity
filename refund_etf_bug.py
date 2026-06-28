import pandas as pd
import json
import os
import glob

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
ledgers = glob.glob(os.path.join(BASE_DIR, 'ETF_Capital_Ledger_*.csv'))

print('=== EXECUTING REFUND FOR ETFs ===\n')

for ledger_path in ledgers:
    df = pd.read_csv(ledger_path)
    if df.empty: continue
    
    total_refund = 0.0
    previous_holdings = {}
    
    for idx, row in df.iterrows():
        try:
            current_holdings = json.loads(row['Holdings_JSON'])
        except:
            current_holdings = {}
            
        for ticker, data in current_holdings.items():
            if isinstance(data, dict):
                units = data.get('units', -1)
                dollars = data.get('dollars', 0.0)
                
                # Check if it is a bugged holding (units = 0, but dollars > 0)
                if units == 0 and dollars > 0:
                    # Check if it was already bugged in the previous row
                    prev_data = previous_holdings.get(ticker, {})
                    prev_units = prev_data.get('units', -1) if isinstance(prev_data, dict) else -1
                    
                    if prev_units != 0:
                        print(f"[{os.path.basename(ledger_path)}] Found lost cash on Date {row['Date']} for {ticker}! Refund: ")
                        total_refund += dollars
                        
        previous_holdings = current_holdings
        
    if total_refund > 0:
        print(f"\nTotal Refund for {os.path.basename(ledger_path)}: ")
        
        # Apply the refund to the FINAL row
        final_cash = float(df.iloc[-1]['Cash'])
        final_equity = float(df.iloc[-1]['Total_Equity'])
        
        df.at[df.index[-1], 'Cash'] = round(final_cash + total_refund, 2)
        df.at[df.index[-1], 'Total_Equity'] = round(final_equity + total_refund, 2)
        
        df.to_csv(ledger_path, index=False)
        print(f"-> Refund successfully applied! New Final Cash: ")
    else:
        print(f"[{os.path.basename(ledger_path)}] No lost cash detected.")
