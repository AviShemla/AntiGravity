import requests

try:
    r = requests.get("http://66.42.118.26/api/race?mode=ETF&persona=BallsForBrains")
    print("ETF_BallsForBrains API:")
    if r.status_code == 200:
        data = r.json()
        print(list(data.keys()))
        print("Dates:", data.get('dates', [])[-3:])
        print("Prod:", data.get('prod', [])[-3:])
except Exception as e:
    print("Error:", e)

try:
    r2 = requests.get("http://66.42.118.26/api/prod_shadow")
    print("\nOlympic API:")
    if r2.status_code == 200:
        data = r2.json()
        print(list(data.keys()))
        print("Dates:", data.get('dates', [])[-3:])
        print("Prod:", data.get('prod', [])[-3:])
        print("Trans:", data.get('trans', [])[-3:])
        print("V1:", data.get('v1', [])[-3:])
except Exception as e:
    print("Error:", e)
