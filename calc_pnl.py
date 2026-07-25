import database_manager as dbm
import pandas as pd

personas = ["BallsForBrains", "ETF_BallsForBrains"]

print("Current Portfolio Valuations (If Liquidated to Cash Today):")
for p in personas:
    df = dbm.execute_query(f"SELECT date, cash, total_equity, holdings_json FROM capital_ledgers WHERE persona='{p}' ORDER BY date DESC LIMIT 1")
    if not df.empty:
        equity = float(df['total_equity'].iloc[0])
        cash = float(df['cash'].iloc[0])
        date = df['date'].iloc[0]
        pnl = equity - 10000.00
        print(f"[{p}] Latest Date: {date}")
        print(f"  Starting Cash: $10,000.00")
        print(f"  Current Total Equity (If Liquidated): ${equity:,.2f}")
        print(f"  Net Profit/Loss: ${pnl:,.2f} ({(pnl/10000.00)*100:.2f}%)")
        print(f"  Current Liquid Cash on Hand: ${cash:,.2f}")
        print(f"  Value in Open Positions: ${equity - cash:,.2f}")
        print("-" * 40)
