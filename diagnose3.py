import sqlite3, json

conn = sqlite3.connect('antigravity.db')

print("=== April 27-28 Conservative Holdings Detail ===")
for date in ['2026-04-27', '2026-04-28']:
    r = conn.execute(
        "SELECT date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status "
        "FROM capital_ledgers WHERE persona='Conservative' AND date=?", (date,)
    ).fetchone()
    if r:
        h = json.loads(r[3])
        p = json.loads(r[4])
        print(f"\n{date}:")
        print(f"  cash={r[1]:.2f}  equity={r[2]:.2f}")
        print(f"  pnl={p}")
        print(f"  holdings={h}")
        print(f"  status=[{r[5]}]")

# Also check what the pending order had for April 28 (probably gone, but let's see if any pending remains)
print("\n=== Pending Orders (if any remain) ===")
rows = conn.execute("SELECT * FROM pending_orders WHERE persona='Conservative'").fetchall()
print(f"  {len(rows)} pending orders found")

# What does the scorecard say the April 27 return was for RF?
import pandas as pd
xls = pd.ExcelFile(r'financial_data\Top5_Bayesian_Scorecard_Formatted.xlsx')
df = pd.read_excel(xls, sheet_name='RF', skiprows=2)
date_col = 'date' if 'date' in df.columns else 'Date'
df = df[pd.to_datetime(df[date_col]) <= pd.to_datetime('2026-04-28')]
print(f"\n=== RF Scorecard (last 3 rows before April 28) ===")
ret_col = 'actual value daily return %' if 'actual value daily return %' in df.columns else 'Actual Daily Return %'
for _, row in df.tail(3).iterrows():
    print(f"  {row[date_col]}: actual_return={row.get(ret_col, 'N/A')}  prob={row.get('Bayesian Probability P(UP)', 'N/A')}")

conn.close()
