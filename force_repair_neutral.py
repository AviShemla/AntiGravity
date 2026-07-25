import database_manager as dbm
df = dbm.execute_query("SELECT cash, total_equity FROM capital_ledgers WHERE persona='ETF_Neutral' AND date='2026-07-23'")
if not df.empty:
    cash = float(df.iloc[0]['cash'])
    eq = float(df.iloc[0]['total_equity'])
    missing = 486.27
    if eq == 10000.00:
        new_cash = cash + missing
        new_eq = eq + missing
        dbm.execute_query("UPDATE capital_ledgers SET cash=?, total_equity=? WHERE persona='ETF_Neutral' AND date='2026-07-23'", [new_cash, new_eq])
        print("ETF_Neutral FORCE REPAIRED.")
    else:
        print("Already fixed.")
