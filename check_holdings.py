import database_manager
import pandas as pd
import json

personas = [
    "Conservative", "Neutral", "Dynamic", "BallsForBrains",
    "ETF_Conservative", "ETF_Neutral", "ETF_Dynamic", "ETF_BallsForBrains"
]

print("=== LIVE HOLDINGS CHECK ===")
for p in personas:
    ledger = database_manager.get_ledger(p)
    if ledger.empty:
        print(f"{p}: No ledger data.")
        continue
    last_row = ledger.iloc[-1]
    holdings = json.loads(last_row['Holdings_JSON']) if isinstance(last_row['Holdings_JSON'], str) else last_row['Holdings_JSON']
    
    print(f"\n[{p}] Date: {last_row['Date']}")
    print(f"Total Equity: {last_row['Total_Equity']} | Cash: {last_row['Cash']}")
    if holdings:
        for ticker, data in holdings.items():
            print(f"  - {ticker}: {data}")
    else:
        print("  - NO HOLDINGS (100% CASH)")
        
    # Check pending order
    po = database_manager.get_pending_order(p)
    if po:
        target_holdings = json.loads(po['target_holdings_json']) if isinstance(po['target_holdings_json'], str) else po['target_holdings_json']
        print(f"  [Pending Order for {po['date']}]")
        if target_holdings:
            for ticker, data in target_holdings.items():
                print(f"    Target -> {ticker}: {data}")
        else:
            print("    Target -> NO HOLDINGS (CASH)")
    else:
        print("  [No Pending Order]")
