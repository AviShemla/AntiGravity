import sqlite3
import json
import pandas as pd

conn = sqlite3.connect(r"C:\Users\AviShemla\AntiGravity\antigravity.db")

pending = pd.read_sql_query("SELECT * FROM pending_orders", conn)

for idx, row in pending.iterrows():
    persona = row['persona']
    target_cash = row['target_cash']
    target_total = row['target_total_equity']
    holdings_json = row['target_holdings_json']
    # Update only the latest row to avoid constraint violations
    conn.execute(
        "UPDATE capital_ledgers SET cash = ?, total_equity = ?, holdings_json = ? WHERE id = (SELECT id FROM capital_ledgers WHERE persona = ? ORDER BY date DESC LIMIT 1)",
        (target_cash, target_total, holdings_json, persona)
    )
    print(f"Forced execution for {persona}: Cash={target_cash}, Holdings={holdings_json}")

conn.commit()
conn.close()
print("\n>>> FORCE EXECUTION COMPLETE: Dashboard should now accurately reflect pending orders.")
