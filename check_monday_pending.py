import urllib.request
import json
import os
from dotenv import load_dotenv

load_dotenv()

url = "https://theoracle-avishe.aws-eu-west-1.turso.io/v2/pipeline"
token = os.environ.get("TURSO_AUTH_TOKEN")

payload = {
    "requests": [
        {"type": "execute", "stmt": {"sql": "SELECT persona, date, target_cash, target_total_equity, target_holdings_json FROM pending_orders"}}
    ]
}

data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
})

try:
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        item = res['results'][0]
        if item['type'] == 'error':
            print("SQL Error:", item['error']['message'])
        else:
            result = item['response']['result']
            cols = [c['name'] for c in result['cols']]
            rows = result['rows']
            print(f"Found {len(rows)} pending order personas:")
            for row in rows:
                vals = [v.get('value') for v in row]
                row_dict = dict(zip(cols, vals))
                print(f"=== {row_dict['persona']} ({row_dict['date']}) ===")
                print(f"  Target Cash: ${row_dict['target_cash']:.2f} | Total Equity: ${row_dict['target_total_equity']:.2f}")
                print(f"  Target Holdings: {row_dict['target_holdings_json']}")
                print("-" * 60)
except Exception as e:
    print("Error:", e)
