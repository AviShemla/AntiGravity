import sqlite3, json

conn = sqlite3.connect('antigravity.db')
rows = conn.execute(
    "SELECT date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status "
    "FROM capital_ledgers WHERE persona='Conservative' AND date <= '2026-05-01' ORDER BY date"
).fetchall()

print("=== Conservative Rows (all) ===")
prev_eq = None
for r in rows:
    h = json.loads(r[3])
    p = json.loads(r[4])
    hv = sum(v['dollars'] if isinstance(v, dict) else float(v) for v in h.values())
    pnl_sum = sum(p.values())
    expected = f"${prev_eq + pnl_sum:.2f}" if prev_eq is not None else "N/A"
    phantom = f"{r[2] - (prev_eq + pnl_sum):+.2f}" if prev_eq is not None else "N/A"
    print(f"  {r[0]} eq={r[2]:.2f} pnl_sum={pnl_sum:.2f} expected={expected} phantom={phantom} cash={r[1]:.2f} hv={hv:.2f} pnl={p}")
    print(f"           status=[{r[5]}]")
    prev_eq = r[2]

conn.close()
