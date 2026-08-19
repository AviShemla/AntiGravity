import urllib.request
import json
import os
import sys
import pandas as pd

load_dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
token = None
if os.path.exists(load_dotenv_path):
    with open(load_dotenv_path, "r") as f:
        for line in f:
            if line.startswith("TURSO_AUTH_TOKEN="):
                token = line.split("=")[1].strip()

url = "https://theoracle-avishe.aws-eu-west-1.turso.io/v2/pipeline"

def query_turso(sql):
    payload = {"requests": [{"type": "execute", "stmt": {"sql": sql}}]}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        response = res['results'][0]['response']['result']
        cols = [c['name'] for c in response['cols']]
        rows = []
        for r in response['rows']:
            row_vals = []
            for cell in r:
                row_vals.append(cell.get('value'))
            rows.append(row_vals)
        return pd.DataFrame(rows, columns=cols)

def generate_db_execution_table():
    print("==========================================================================================================================")
    print("=== TURSO DB 100% BACKED PREDICTION & ALLOCATION BREAKDOWN (STOCKS & ETFs BY PERSONA) ===")
    print("==========================================================================================================================")

    # 1. Query pending_orders for Staged Holdings
    df_pending = query_turso("SELECT persona, date, target_cash, target_holdings_json FROM pending_orders")
    
    # 2. Query etf_scorecards_master for latest Model Recommendations (Buy/Sell/Hold signals)
    try:
        df_scorecards = query_turso("SELECT ticker, persona, date, prob, expected_return, recommendation, kelly_allocation FROM etf_scorecards_master WHERE date >= (SELECT MAX(date) FROM etf_scorecards_master) ORDER BY persona, prob DESC")
    except:
        df_scorecards = pd.DataFrame()

    records = []
    
    for idx, row in df_pending.iterrows():
        p = row['persona']
        dt = str(row['date'])[:10]
        cash = float(row['target_cash'])
        holdings = json.loads(row['target_holdings_json']) if row['target_holdings_json'] else {}
        
        mode = "ETF" if p.startswith("ETF_") else "Single Stock"
        persona_name = p.replace("ETF_", "")
        
        if not holdings:
            records.append({
                "Universe": mode,
                "Persona": persona_name,
                "Asset / Ticker": "ALL TICKERS",
                "Model Prediction Signal": "HOLD / PROTECT CAPITAL",
                "Win Prob P(UP)": "N/A",
                "Staged Target Allocation": f"${cash:,.2f} (100% Cash)",
                "Action": "HOLD CASH (NO BUY TRADES)"
            })
        else:
            for asset, details in holdings.items():
                val = float(details.get('dollars', 0.0)) if isinstance(details, dict) else float(details)
                units = details.get('units', 0) if isinstance(details, dict) else 0
                
                # Fetch matching scorecard prediction if available
                prob_str = "N/A"
                rec_str = "BUY / ALLOCATE"
                if not df_scorecards.empty:
                    sc_match = df_scorecards[(df_scorecards['ticker'] == asset) & (df_scorecards['persona'] == persona_name)]
                    if not sc_match.empty:
                        prob_val = float(sc_match.iloc[0]['prob'])
                        prob_str = f"{prob_val:.1%}"
                        rec_str = str(sc_match.iloc[0]['recommendation']).upper()

                records.append({
                    "Universe": mode,
                    "Persona": persona_name,
                    "Asset / Ticker": asset,
                    "Model Prediction Signal": rec_str,
                    "Win Prob P(UP)": prob_str,
                    "Staged Target Allocation": f"${val:,.2f} ({units} shares)",
                    "Action": f"STAGED BUY (${val:,.2f})"
                })

    df_out = pd.DataFrame(records)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(df_out.to_string(index=False))
    print("==========================================================================================================================")

    os._exit(0)

if __name__ == "__main__":
    generate_db_execution_table()
