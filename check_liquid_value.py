import database_manager as dbm

personas = ["Conservative", "Neutral", "Dynamic", "BallsForBrains", "ETF_Conservative", "ETF_Neutral", "ETF_Dynamic", "ETF_BallsForBrains"]

print("| Broker Persona | Starting Capital | Liquidable Value (Total Equity) | Net PnL (All-Time) |")
print("|---|---|---|---|")

total_start = 0
total_liquid = 0

for p in personas:
    df = dbm.execute_query(f"SELECT total_equity FROM capital_ledgers WHERE persona='{p}' ORDER BY date DESC LIMIT 1")
    if not df.empty:
        te = float(df.iloc[0]['total_equity'])
        start = 10000.0
        pnl = te - start
        
        total_start += start
        total_liquid += te
        
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        print(f"| {p} | ${start:,.2f} | ${te:,.2f} | {pnl_str} |")

total_pnl = total_liquid - total_start
total_pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
print("| **GRAND TOTAL** | **${:,.2f}** | **${:,.2f}** | **{}** |".format(total_start, total_liquid, total_pnl_str))
