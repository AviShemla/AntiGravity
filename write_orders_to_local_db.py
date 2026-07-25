import sqlite3
import json

conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/financial_data/ag_pipeline_fallback.db')
cursor = conn.cursor()

path = "C:/Users/AviShemla/AntiGravity/financial_data/Pending_Orders.json"
with open(path, "r") as f:
    data = json.load(f)

for persona, info in data.items():
    cursor.execute("DELETE FROM pending_orders WHERE persona=?", (persona,))
    cursor.execute(
        "INSERT INTO pending_orders (persona, date, target_cash, target_total_equity, target_holdings_json, daily_pnl_json, executed_intraday_trades_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            persona,
            info["Date"],
            info["Target_Cash"],
            info["Target_Total_Equity"],
            json.dumps(info.get("Target_Holdings", {})),
            json.dumps(info.get("Daily_PnL_JSON", {})),
            json.dumps(info.get("Executed_Intraday_Trades", {}))
        )
    )

conn.commit()
conn.close()
print("ORDERS INJECTED INTO LOCAL SQLITE DB.")
