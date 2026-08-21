import sqlite3

def list_tables():
    conn = sqlite3.connect('Capital_Ledger.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables:", tables)

list_tables()
