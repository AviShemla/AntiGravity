import requests

try:
    r = requests.get("http://66.42.118.26/api/race?mode=ETF")
    if r.status_code == 200:
        data = r.json()
        print("ETF_BallsForBrains Dates:", data['BallsForBrains']['dates'][-3:])
        print("ETF_BallsForBrains Equity:", data['BallsForBrains']['total_equity'][-3:])
        print("ETF_Dynamic Equity:", data['Dynamic']['total_equity'][-3:])
except Exception as e:
    print("Error:", e)
