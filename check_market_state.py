import database_manager as dbm

try:
    df = dbm.execute_query("SELECT date, action, reason FROM global_market_state ORDER BY date DESC LIMIT 5")
    if not df.empty:
        print("Global Market State History:")
        print(df.to_string())
except:
    print("global_market_state table not found.")

try:
    df2 = dbm.execute_query("SELECT * FROM market_momentum WHERE date > '2026-07-20' ORDER BY date DESC LIMIT 5")
    if not df2.empty:
        print("\nMarket Momentum History:")
        print(df2.to_string())
except:
    print("market_momentum table not found.")
