import database_manager
import json

orders = database_manager.execute_query("SELECT persona, target_holdings_json FROM pending_orders WHERE date='2026-07-21'")
print("--- STOCKS & ETFS BROKER ORDERS ---")
for _, row in orders.iterrows():
    persona = row['persona']
    holdings = json.loads(row['target_holdings_json'])
    print(f"\n[{persona}]")
    for ticker, info in holdings.items():
        print(f"  - {ticker}: {info['units']} units @ ${info.get('dollars', 0.0):.2f}")
