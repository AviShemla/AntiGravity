import database_manager
import json

orders = database_manager.execute_query("SELECT persona, target_holdings_json FROM pending_orders WHERE date='2026-07-21'")
ledgers = database_manager.execute_query("SELECT persona, holdings_json FROM capital_ledgers WHERE date='2026-07-20'")

yesterday_holdings = {}
for _, row in ledgers.iterrows():
    try:
        yesterday_holdings[row['persona']] = json.loads(row['holdings_json'])
    except:
        yesterday_holdings[row['persona']] = {}

print("--- STOCKS & ETFS BROKER ORDERS DELTA ---")
for _, row in orders.iterrows():
    persona = row['persona']
    target_holdings = json.loads(row['target_holdings_json'])
    prev_holdings = yesterday_holdings.get(persona, {})
    
    print(f"\n[{persona}]")
    
    # Check for SELLs (in prev but not in target, or reduced units)
    for ticker, prev_info in prev_holdings.items():
        prev_units = prev_info.get('units', 0)
        if ticker not in target_holdings:
            print(f"  - {ticker}: SELL {prev_units} units (Close Position)")
        else:
            target_units = target_holdings[ticker].get('units', 0)
            if target_units < prev_units:
                print(f"  - {ticker}: SELL {prev_units - target_units} units (Reduce Position)")
                
    # Check for BUYs or HOLDs
    for ticker, target_info in target_holdings.items():
        target_units = target_info.get('units', 0)
        prev_info = prev_holdings.get(ticker, {})
        prev_units = prev_info.get('units', 0)
        
        if target_units > prev_units:
            print(f"  - {ticker}: BUY {target_units - prev_units} units (Target: {target_units})")
        elif target_units == prev_units and target_units > 0:
            print(f"  - {ticker}: HOLD {target_units} units")

