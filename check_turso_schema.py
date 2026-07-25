import os
import requests
from dotenv import load_dotenv
import json

load_dotenv("C:/Users/AviShemla/AntiGravity/.env")
TURSO_URL = os.environ.get("TURSO_DATABASE_URL").replace("libsql://", "https://")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")
headers = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}

data = {
    "requests": [
        {"type": "execute", "stmt": {"sql": "PRAGMA table_info(pending_orders)", "args": []}},
        {"type": "close"}
    ]
}

response = requests.post(f"{TURSO_URL}/v2/pipeline", json=data, headers=headers)
print(json.dumps(response.json(), indent=2))
