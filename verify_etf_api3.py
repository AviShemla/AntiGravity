import requests

try:
    r = requests.get("http://66.42.118.26/api/race?mode=ETF")
    if r.status_code == 200:
        data = r.json()
        print("ETF_BallsForBrains Dates:", data['BallsForBrains']['dates'][-4:])
        print("ETF_BallsForBrains Equity:", data['BallsForBrains']['values'][-4:])
        print("ETF_Dynamic Equity:", data['Dynamic']['values'][-4:])
except Exception as e:
    print("Error:", e)

try:
    r2 = requests.get("http://66.42.118.26/api/prod_shadow")
    print("\nOlympic API:")
    if r2.status_code == 200:
        data = r2.json()
        print("Dates:", data.get('dates', [])[-4:])
        print("Prod:", data.get('prod', [])[-4:])
except Exception as e:
    print("Error:", e)
