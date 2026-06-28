import sqlite3, json, pandas as pd

conn = sqlite3.connect('antigravity.db')

print("=== Conservative April 27-29 ===")
df = pd.read_sql("SELECT date, cash, total_equity, holdings_json, daily_pnl_json FROM capital_ledgers WHERE persona='Conservative' AND date BETWEEN '2026-04-26' AND '2026-04-30' ORDER BY date", conn)
for _, r in df.iterrows():
    h = json.loads(r['holdings_json'])
    p = json.loads(r['daily_pnl_json'])
    holdings_val = sum(x['dollars'] if isinstance(x, dict) else x for x in h.values())
    print(f"  date={r['date']} cash={r['cash']:.2f} equity={r['total_equity']:.2f} holdings_val={holdings_val:.2f} pnl={p}")

print()
print("=== BallsForBrains April 29 - May 2 ===")
df = pd.read_sql("SELECT date, cash, total_equity, holdings_json, daily_pnl_json FROM capital_ledgers WHERE persona='BallsForBrains' AND date BETWEEN '2026-04-28' AND '2026-05-02' ORDER BY date", conn)
for _, r in df.iterrows():
    h = json.loads(r['holdings_json'])
    p = json.loads(r['daily_pnl_json'])
    holdings_val = sum(x['dollars'] if isinstance(x, dict) else x for x in h.values())
    print(f"  date={r['date']} cash={r['cash']:.2f} equity={r['total_equity']:.2f} holdings_val={holdings_val:.2f} pnl_sum={sum(p.values()):.2f} pnl={p}")


print()
print("=== CHECK: cash + holdings_val == total_equity for all rows? ===")
for persona in ['BallsForBrains', 'Conservative', 'Neutral', 'Dynamic']:
    df = pd.read_sql(f"SELECT date, cash, total_equity, holdings_json FROM capital_ledgers WHERE persona='{persona}' ORDER BY date", conn)
    mismatches = 0
    for _, r in df.iterrows():
        h = json.loads(r['holdings_json'])
        hv = sum(x['dollars'] if isinstance(x, dict) else float(x) for x in h.values())
        actual_sum = round(r['cash'] + hv, 2)
        recorded = round(r['total_equity'], 2)
        if abs(actual_sum - recorded) > 0.10:
            print(f"  {persona} {r['date']}: cash={r['cash']:.2f} + holdings={hv:.2f} = {actual_sum:.2f} but total_equity={recorded:.2f} | MISMATCH={actual_sum-recorded:+.2f}")
            mismatches += 1
    if mismatches == 0:
        print(f"  {persona}: all rows cash+holdings == total_equity OK")

conn.close()
