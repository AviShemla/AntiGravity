#!/usr/bin/env python3
"""
=============================================================================
PERMANENT FAST ALL-8 PERSONAS STATUS SCRIPT
=============================================================================
Instantly queries live dashboard API and prints clean empirical standings for all 8 personas in < 1 second.
"""

import urllib.request
import json
import pandas as pd

def fetch_all_8_standings():
    print("=================================================================")
    print("   100% EMPIRICAL LIVE STANDINGS FOR ALL 8 TRADING PERSONAS       ")
    print("=================================================================")
    
    url_single = "http://127.0.0.1:80/api/race?mode=Single"
    url_etf = "http://127.0.0.1:80/api/race?mode=ETF"
    
    rows = []
    
    # 1. Fetch Single Stock Personas
    try:
        req = urllib.request.urlopen(url_single, timeout=3)
        data = json.loads(req.read().decode())
        for persona, pdata in data.items():
            if pdata.get('values'):
                latest_eq = pdata['values'][-1]
                if latest_eq is not None:
                    pnl = latest_eq - 10000.0
                    pnl_pct = (pnl / 10000.0) * 100.0
                    rows.append({'Persona': persona, 'Category': 'Stock', 'Total Equity': latest_eq, 'PnL ($)': pnl, 'PnL (%)': pnl_pct})
    except Exception as e:
        print(f"Error querying Stock API: {e}")

    # 2. Fetch Multi-Sector ETF Personas
    try:
        req = urllib.request.urlopen(url_etf, timeout=3)
        data = json.loads(req.read().decode())
        for persona, pdata in data.items():
            if pdata.get('values'):
                latest_eq = pdata['values'][-1]
                if latest_eq is not None:
                    pnl = latest_eq - 10000.0
                    pnl_pct = (pnl / 10000.0) * 100.0
                    full_name = f"ETF_{persona}" if not persona.startswith("ETF_") else persona
                    rows.append({'Persona': full_name, 'Category': 'ETF', 'Total Equity': latest_eq, 'PnL ($)': pnl, 'PnL (%)': pnl_pct})
    except Exception as e:
        print(f"Error querying ETF API: {e}")
        
    if rows:
        df = pd.DataFrame(rows)
        df = df.sort_values('Total Equity', ascending=False).reset_index(drop=True)
        df.index = df.index + 1
        print(df.to_string())
    else:
        print("❌ WARNING: Could not retrieve persona standings from API.")
        
    print("=================================================================")

if __name__ == "__main__":
    fetch_all_8_standings()
