import database_manager as db
try:
    res = db.execute_query("SELECT persona, date, total_equity, intraday_status FROM capital_ledgers WHERE date='2026-07-24'")
    print(res)
except Exception as e:
    print(f"Error: {e}")
