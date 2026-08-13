import database_manager
try:
    df = database_manager.execute_query("SELECT DISTINCT Ticker FROM stock_scorecards_master WHERE date='2026-08-12'")
    print("TICKERS:", list(df['Ticker']))
except Exception as e:
    print("ERROR:", e)
