import json
import os
import database_manager

path = "C:/Users/AviShemla/AntiGravity/financial_data/Pending_Orders.json"
with open(path, "r") as f:
    data = json.load(f)

for persona, info in data.items():
    print(f"Pushing {persona} to Turso...")
    try:
        # Pass exactly the kwargs expected
        database_manager.save_pending_order(
            persona=info["Persona"],
            target_date=info["Date"],
            target_cash=info["Target_Cash"],
            target_total_equity=info["Target_Total_Equity"],
            target_holdings=info["Target_Holdings"],
            daily_pnl=info.get("Daily_PnL_JSON", {}),
            executed_trades=info.get("Executed_Intraday_Trades", {})
        )
        print(f"Successfully pushed {persona}")
    except Exception as e:
        print(f"Failed to push {persona}: {e}")

print("TURSO PUSH COMPLETE.")
