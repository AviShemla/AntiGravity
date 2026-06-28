import sqlite3, json

conn = sqlite3.connect('antigravity.db')
cursor = conn.cursor()

r27 = cursor.execute("SELECT date, cash, total_equity, holdings_json, daily_pnl_json FROM capital_ledgers WHERE persona='Conservative' AND date='2026-04-27'").fetchone()
cash27 = r27[1]
eq27 = r27[2]
h27 = json.loads(r27[3])
pnl27 = json.loads(r27[4])

print("April 27:")
print(f"  Cash={cash27}, Eq={eq27}, Holdings={h27}, PnL={pnl27}")

allocated = h27['RF']['dollars']
pnl_rf = allocated * 0.01801152707767262
print(f"\nVirtual Broker calculated PnL for RF: {pnl_rf}")

settled_eq = cash27 + allocated + pnl_rf
print(f"Settled Eq: {settled_eq}")

target_cash = settled_eq  # Because no new holdings
print(f"Target Cash: {target_cash}")

state_daily_pnl = {'RF': pnl_rf}
final_cash = target_cash
current_holdings = h27
final_holdings = {}

live_price = 28.06
executed_memory = {'RF': {'type': 'SELL', 'price': live_price}}

print("\nTracker Processing Executed Memory:")
for ticker, record in executed_memory.items():
    if record['type'] == 'SELL':
        if ticker in current_holdings and ticker not in final_holdings:
            print(f"  Hit branch: Pending overnight sell")
            units = current_holdings[ticker]['units']
            allocated_dollars = units * current_holdings[ticker]['price']
            broker_credited = allocated_dollars + state_daily_pnl.get(ticker, 0.0)
            
            sale_value = units * record['price']
            
            print(f"  units={units}, allocated_dollars={allocated_dollars}, broker_credited={broker_credited}, sale_value={sale_value}")
            
            final_cash -= broker_credited
            final_cash += sale_value
            
            state_daily_pnl[ticker] = sale_value - allocated_dollars
            
            print(f"  Final Cash becomes: {final_cash}")
            print(f"  New PnL: {state_daily_pnl[ticker]}")

print(f"\nEnd Result: Cash={final_cash}, PnL={state_daily_pnl}")

conn.close()
