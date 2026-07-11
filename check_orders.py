import sys
sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
import database_manager
import json

conn = database_manager.get_connection()
print("--- PENDING ORDERS (Sniper Targets) ---")
res = conn._client.execute("SELECT persona, date, target_holdings_json FROM pending_orders")
if res.rows:
    for row in res.rows:
        persona, date, target = row
        print(f"[{persona}] Target Date: {date} -> {target}")
else:
    print("No pending orders found.")

print("\n--- CURRENT HOLDINGS (Live Ledger) ---")
personas = ['Conservative', 'Neutral', 'BallsForBrains', 'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains']
for p in personas:
    res = conn._client.execute(f"SELECT date, holdings_json FROM capital_ledgers WHERE persona='{p}' ORDER BY date DESC LIMIT 1")
    if res.rows:
        date, holdings = res.rows[0]
        holdings_dict = json.loads(holdings) if isinstance(holdings, str) else holdings
        items = [f"{k} (${v.get('dollars', 0):.2f})" if isinstance(v, dict) else f"{k} (${v:.2f})" for k, v in holdings_dict.items()]
        print(f"[{p}] {date} -> {', '.join(items) if items else 'CASH ONLY'}")
    else:
        print(f"[{p}] NO DATA")
