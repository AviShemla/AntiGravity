import requests

try:
    r = requests.get("http://66.42.118.26/api/race?mode=ETF&persona=BallsForBrains")
    print("ETF_BallsForBrains API:")
    if r.status_code == 200:
        data = r.json()
        print("Dates:", data.get('dates', [])[-3:])
        print("Total Equity:", data.get('total_equity', [])[-3:])
        print("Shadow Equity:", data.get('shadow_equity', [])[-3:])
    else:
        print("Status:", r.status_code)
except Exception as e:
    print("Error:", e)

try:
    r2 = requests.get("http://66.42.118.26/api/prod_shadow")
    print("\nOlympic API:")
    if r2.status_code == 200:
        data = r2.json()
        print("Dates:", data.get('dates', [])[-3:])
        print("Cons:", data.get('cons_equity', [])[-3:])
        print("Dyn:", data.get('dyn_equity', [])[-3:])
    else:
        print("Status:", r2.status_code)
except Exception as e:
    print("Error:", e)
