import os
import sys
import pandas as pd
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager

conn = database_manager.get_connection()
personas = ['Conservative', 'Neutral', 'BallsForBrains', 'ETF_Conservative', 'ETF_Neutral', 'ETF_BallsForBrains']

print("--- CURRENT HOLDINGS AND PnL STATUS ---")
for p in personas:
    res = conn._client.execute(f"SELECT date, holdings_json, daily_pnl_json FROM capital_ledgers WHERE persona='{p}' ORDER BY date DESC LIMIT 1")
    if res.rows:
        row = res.rows[0]
        print(f"\n[{p}] Date: {row[0]}")
        holdings = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        pnl = json.loads(row[2]) if isinstance(row[2], str) else row[2]
        
        # Format holdings
        holdings_str = ", ".join([f"{k} (${v.get('dollars', 0):.2f})" if isinstance(v, dict) else f"{k} (${v:.2f})" for k, v in holdings.items()])
        if not holdings_str: holdings_str = "CASH ONLY"
        print(f"  Holdings: {holdings_str}")
        
        # Format PnL
        pnl_str = ", ".join([f"{k}: ${v:.2f}" for k, v in pnl.items()])
        if not pnl_str: pnl_str = "None"
        print(f"  Today's Realized PnL: {pnl_str}")
    else:
        print(f"\n[{p}] NO DATA")

print("\n--- PRED VS ACTUAL (from Scorecard) ---")
try:
    df_stock = pd.read_excel(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Top5_Bayesian_Scorecard_Formatted.xlsx'), sheet_name=None)
    print("Stock Predictions:")
    for sheet_name, df in df_stock.items():
        latest = df.tail(1).iloc[0]
        if 'Bayesian_Expected_Return' in df.columns and 'Actual_Return' in df.columns:
             print(f"  {sheet_name}: Pred={latest['Bayesian_Expected_Return']:.2f}% | Actual={latest['Actual_Return']:.2f}%")
        elif 'Bayesian_Prediction' in df.columns:
             print(f"  {sheet_name}: Pred={latest['Bayesian_Prediction']:.2f}% | Close={latest.get('Close', 'N/A')}")
        else:
             print(f"  {sheet_name}: {latest.to_dict()}")
except Exception as e:
    print("Error reading stock scorecard:", e)

try:
    xls = pd.ExcelFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'All_ETFs_Scorecard.xlsx'))
    print("\nETF Predictions:")
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name, skiprows=2)
        latest = df.tail(1).iloc[0]
        pred = latest.get('Expected Return %', 0)
        actual = latest.get('actual value daily return %', 'N/A')
        print(f"  {sheet_name}: Pred={pred:.2f}% | Actual={actual}")
except Exception as e:
    print("Error reading ETF scorecard:", e)
