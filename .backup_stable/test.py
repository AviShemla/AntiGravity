import requests
try:
    res = requests.get('http://127.0.0.1:8000/api/holdings?persona=BallsForBrains&mode=Single')
    print("Status:", res.status_code)
    data = res.json()
    print("Keys in response:", data.keys())
    print("Breakdown length:", len(data.get('breakdown', [])))
except Exception as e:
    print("Error:", e)
