import sqlite3
import json

conn = sqlite3.connect('antigravity.db')
c = conn.cursor()

print("=================================================================")
print("=== WEEKEND STATUS REPORT: FRIDAY CLOSE (JUNE 26) ===")
print("=================================================================\n")

print("--- BROKER LEDGER SUMMARY ---")
personas = ['BallsForBrains', 'ETF_BallsForBrains', 'Dynamic', 'Neutral', 'Conservative', 'ETF_Dynamic', 'ETF_Neutral', 'ETF_Conservative']

for persona in personas:
    c.execute("""
        SELECT date, cash, total_equity, holdings_json, daily_pnl_json, intraday_status 
        FROM capital_ledgers 
        WHERE persona = ? 
        ORDER BY date DESC LIMIT 1
    """, (persona,))
    row = c.fetchone()
    
    if row:
        date, cash, equity, holdings_raw, pnl_raw, status = row
        holdings = json.loads(holdings_raw) if holdings_raw else {}
        pnl = json.loads(pnl_raw) if pnl_raw else {}
        total_pnl = sum(pnl.values()) if pnl else 0
        tickers = list(holdings.keys())
        
        print(f"[{persona}] - Last Update: {date}")
        print(f"  Equity: ${equity:,.2f} (Cash: ${cash:,.2f})")
        print(f"  Status: {status}")
        print(f"  Holdings: {tickers}")
        print(f"  Daily PnL Booked: ${total_pnl:+.2f}\n")
    else:
        print(f"[{persona}] - No data found.\n")

print("--- EXECUTED TRADES (June 26) ---")
c.execute("""
    SELECT date, persona, ticker, action, units, price, pnl
    FROM executed_trades 
    WHERE date LIKE '2026-06-26%'
    ORDER BY date ASC
""")
trades = c.fetchall()

if not trades:
    print("No trades executed on June 26.")
else:
    for t in trades:
        ts, persona, ticker, action, shares, price, pnl = t
        pnl_str = f" | PnL: ${pnl:+.2f}" if pnl is not None else ""
        print(f"  [{ts}] {persona}: {action} {shares} shares of {ticker} @ ${price:.2f}{pnl_str}")

conn.close()
