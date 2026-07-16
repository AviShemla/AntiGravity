import sys
try:
    import database_manager
    date_str = "2026-07-15"
    df = database_manager.execute_query(f"SELECT total_equity FROM capital_ledgers WHERE persona='BallsForBrains' AND date LIKE '{date_str}%'")
    if not df.empty:
        print("Success:", float(df['total_equity'].iloc[-1]))
    else:
        print("Empty DataFrame returned")
except Exception as e:
    print("Exception occurred:", e)
