import os
import sys
from dotenv import load_dotenv
import libsql_client

sys.path.append('C:\\Users\\AviShemla\\AntiGravity')
load_dotenv('C:\\Users\\AviShemla\\AntiGravity\\.env')
url = os.environ.get("TURSO_DATABASE_URL")
token = os.environ.get("TURSO_AUTH_TOKEN")

with open('purge_out.txt', 'w') as f:
    f.write(f"Connecting DIRECTLY to Turso to PURGE pending orders: {url}\n")
    try:
        client = libsql_client.create_client_sync(url=url, auth_token=token)
        res = client.execute("DELETE FROM pending_orders")
        f.write(f"Purged all pending orders. Rows affected: {res.rows_affected}\n")
        client.close()
    except Exception as e:
        f.write(f"Turso Connection Error: {e}\n")

os._exit(0)
