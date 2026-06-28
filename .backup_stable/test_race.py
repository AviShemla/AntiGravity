import requests

try:
    res = requests.get("http://127.0.0.1:8000/api/race?mode=Single")
    print(res.status_code)
    data = res.json()
    print("Keys:", data.keys())
    for k, v in data.items():
        print(f"{k} -> length {len(v['dates'])}")
except Exception as e:
    print("Error:", e)
