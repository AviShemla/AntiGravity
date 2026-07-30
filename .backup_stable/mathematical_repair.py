import database_manager as dbm
import json

personas = ["ETF_Conservative", "ETF_Neutral", "ETF_Dynamic", "ETF_BallsForBrains"]

print("--- MATHEMATICAL REPAIR ---")
for p in personas:
    df = dbm.execute_query(f"SELECT date, cash, total_equity FROM capital_ledgers WHERE persona='{p}' AND date IN ('2026-07-22', '2026-07-23') ORDER BY date ASC")
    if len(df) == 2:
        eq_22 = float(df.iloc[0]['total_equity'])
        cash_23 = float(df.iloc[1]['cash'])
        eq_23 = float(df.iloc[1]['total_equity'])
        
        missing_equity = eq_22 - 10000.00
        
        new_cash = cash_23 + missing_equity
        new_eq = eq_23 + missing_equity
        
        print(f"[{p}] Missing Equity: {missing_equity:.2f}. Old Eq23: {eq_23}. New Eq23: {new_eq:.2f}. New Cash: {new_cash:.2f}")
        
        dbm.execute_query("UPDATE capital_ledgers SET cash=?, total_equity=? WHERE persona=? AND date='2026-07-23'", [new_cash, new_eq, p])
        print(f"[{p}] REPAIRED.")
