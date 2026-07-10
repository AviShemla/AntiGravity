from database_manager import get_connection

def fix():
    client = get_connection()._client
    try:
        client.execute("""
            UPDATE capital_ledgers
            SET total_equity = 10678.70,
                cash = cash + 18.27
            WHERE persona = 'ETF_Balls For Brain' AND date = '2026-07-07'
        """)
        print("Ledger fixed.")
    finally:
        client.close()

fix()
