import os
import pandas as pd
import json

print("=== PREDICTIONS & RECOMMENDATIONS ===")

try:
    s = pd.read_excel(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Top5_Bayesian_Scorecard_Formatted.xlsx'), sheet_name=None)
    print("\n[STOCKS]")
    for k, v in s.items():
        if k != 'Sheet1' and not v.empty:
            ret = v.iloc[-1].get("Next Day Expected Return", 0) * 100
            prob = v.iloc[-1].get("Win Probability", 0) * 100
            print(f"  {k}: Pred Return={ret:.2f}%, WinProb={prob:.1f}%")
except Exception as e:
    print("Stocks Error:", e)

try:
    e = pd.read_excel(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'All_ETFs_Scorecard.xlsx'), sheet_name=None)
    print("\n[ETFs]")
    for k, v in e.items():
        if k != 'Sheet1' and not v.empty:
            ret = v.iloc[-1].get("Next Day Expected Return", 0) * 100
            prob = v.iloc[-1].get("Win Probability", 0) * 100
            print(f"  {k}: Pred Return={ret:.2f}%, WinProb={prob:.1f}%")
except Exception as exc:
    print("ETFs Error:", exc)

import urllib.request
print("\n=== CURRENT ACTUALS (BALLS FOR BRAINS PERSONA) ===")
try:
    res = urllib.request.urlopen('http://66.42.118.26:80/api/holdings?persona=BallsForBrains&mode=Single').read().decode()
    data = json.loads(res)
    print(f"Stock Equity: ${data['total_equity']:.2f}")
    print(f"Stock Return: {data['total_return']:.2f}%")
    print(f"Current Allocations: {json.dumps(data['allocations'])}")
except Exception as e:
    print("Actuals Error:", e)

try:
    res = urllib.request.urlopen('http://66.42.118.26:80/api/holdings?persona=BallsForBrains&mode=ETF').read().decode()
    data = json.loads(res)
    print(f"ETF Equity:   ${data['total_equity']:.2f}")
    print(f"ETF Return:   {data['total_return']:.2f}%")
    print(f"Current ETF Allocations: {json.dumps(data['allocations'])}")
except Exception as e:
    print("ETF Actuals Error:", e)
