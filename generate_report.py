import sqlite3
import pandas as pd
import json

conn = sqlite3.connect('antigravity.db')

print('=== ACTUAL EOD EXECUTIONS (June 24th) ===')
ledgers = pd.read_sql("SELECT persona, holdings_json, daily_pnl_json, intraday_status FROM capital_ledgers WHERE date='2026-06-24'", conn)
for _, row in ledgers.iterrows():
    print(f"[{row['persona']}] Intraday Tracker Status: {row['intraday_status']}")
    try:
        h = json.loads(row['holdings_json'])
        pnl = json.loads(row['daily_pnl_json'])
        for t, data in h.items():
            print(f"  -> HOLDING: {t} | PnL Generated: ${pnl.get(t, 0.0)}")
        if not h:
            print(f"  -> All assets liquidated to CASH.")
    except:
        pass
    print()

print('=== PENDING ORDERS / PREDICTIONS (June 25th) ===')
pending = pd.read_sql("SELECT persona, target_holdings_json, executed_intraday_trades_json FROM pending_orders", conn)
for _, row in pending.iterrows():
    print(f"[{row['persona']}]")
    try:
        h = json.loads(row['target_holdings_json'])
        ex = json.loads(row['executed_intraday_trades_json'])
        for t, data in h.items():
            print(f"  -> TARGET BUY/HOLD: {t} | Target Alloc: ${data.get('dollars', 0):.2f}")
        if not h:
            print(f"  -> TARGET: Sit in CASH.")
        for t, data in ex.items():
            print(f"  -> INTRADAY EXECUTED ({data.get('type')}): {t} at ${data.get('price')}")
    except:
        pass
    print()

conn.close()
