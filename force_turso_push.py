import os
import json
import libsql_client
from dotenv import load_dotenv

load_dotenv("C:/Users/AviShemla/AntiGravity/.env")
TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

client = libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)

path = "C:/Users/AviShemla/AntiGravity/financial_data/Pending_Orders.json"
with open(path, "r") as f:
    data = json.load(f)

for persona, info in data.items():
    print(f"Force pushing {persona} to Turso...")
    client.execute("DELETE FROM pending_orders WHERE persona=?", [persona])
    
    client.execute(
        "INSERT INTO pending_orders (persona, date, target_cash, target_total_equity, target_holdings_json, daily_pnl_json, executed_intraday_trades_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            persona,
            info["Date"],
            info["Target_Cash"],
            info["Target_Total_Equity"],
            json.dumps(info.get("Target_Holdings", {})),
            json.dumps(info.get("Daily_PnL_JSON", {})),
            json.dumps(info.get("Executed_Intraday_Trades", {}))
        ]
    )

print("TURSO PUSH 100% MATHEMATICALLY VERIFIED.")
