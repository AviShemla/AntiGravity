import os
import sys
from dotenv import load_dotenv
import libsql_client

sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
load_dotenv('C:\\Users\\AviShemla\\AntiGravity\\.env')
url = os.environ.get("TURSO_DATABASE_URL")
token = os.environ.get("TURSO_AUTH_TOKEN")

with open('turso_out.txt', 'w') as f:
    f.write(f"Connecting DIRECTLY to Turso: {url}\n")
    try:
        client = libsql_client.create_client_sync(url=url, auth_token=token)
        res = client.execute("SELECT persona, date FROM pending_orders ORDER BY date DESC")
        f.write("\n--- TURSO PENDING ORDERS DATES ---\n")
        for row in res.rows:
            f.write(f"{row[0]}: {row[1]}\n")
            
        res2 = client.execute("SELECT persona, date, COUNT(*) FROM capital_ledgers GROUP BY persona, date ORDER BY date DESC LIMIT 15")
        f.write("\n--- TURSO CAPITAL LEDGERS (LATEST) ---\n")
        for row in res2.rows:
            f.write(f"{row[0]} | Date: {row[1]}\n")
            
        client.close()
    except Exception as e:
        f.write(f"Turso Connection Error: {e}\n")

os._exit(0)
