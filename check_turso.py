import database_manager
try:
    df = database_manager.get_ledger("ETF_Conservative")
    if not df.empty:
        print("Latest Date in Turso ETF_Conservative:", df['date'].max())
    else:
        print("Empty")
except Exception as e:
    print(f"Error: {e}")
