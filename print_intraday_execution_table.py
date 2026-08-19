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
    print("=== TURSO DB 100% BACKED PREDICTION & ALLOCATION BREAKDOWN (ALL 8 PERSONAS: STOCKS & ETFs) ===")
    print("==========================================================================================================================")

    # 1. Query pending_orders for Staged Holdings across all 8 personas
    df_pending = query_turso("SELECT persona, date, target_cash, target_holdings_json FROM pending_orders")
    
    # 2. Query etf_scorecards_master for latest Model Recommendations & Win Probabilities
    try:
        df_scorecards = query_turso("SELECT ticker, persona, date, prob, expected_return, recommendation, kelly_allocation FROM etf_scorecards_master WHERE date >= (SELECT MAX(date) FROM etf_scorecards_master) ORDER BY persona, prob DESC")
    except:
        df_scorecards = pd.DataFrame()

    records = []
    
    # Ensure all 8 personas are queried explicitly
    all_personas = [
        ("Single Stock", "Conservative"), ("Single Stock", "Neutral"), ("Single Stock", "BallsForBrains"), ("Single Stock", "Dynamic"),
        ("Multi-Sector ETF", "ETF_Conservative"), ("Multi-Sector ETF", "ETF_Neutral"), ("Multi-Sector ETF", "ETF_BallsForBrains"), ("Multi-Sector ETF", "ETF_Dynamic")
    ]
    
    pending_dict = {}
    if not df_pending.empty:
        for _, r in df_pending.iterrows():
            pending_dict[r['persona']] = r

    # 3. Query capital_ledgers for live holdings as fallback if pending_orders row is missing
    df_ledgers = query_turso("SELECT persona, date, cash, total_equity, holdings_json FROM capital_ledgers WHERE date = (SELECT MAX(date) FROM capital_ledgers)")
    ledger_dict = {}
    if not df_ledgers.empty:
        for _, r in df_ledgers.iterrows():
            ledger_dict[r['persona']] = r

    for universe_type, p_key in all_personas:
        row = pending_dict.get(p_key)
        if row is None or pd.isna(row['target_holdings_json']) or not row['target_holdings_json']:
            row = ledger_dict.get(p_key)

        persona_display = p_key.replace("ETF_", "")
        
        holdings_raw = row['target_holdings_json'] if (row is not None and 'target_holdings_json' in row and not pd.isna(row['target_holdings_json'])) else (row['holdings_json'] if (row is not None and 'holdings_json' in row and not pd.isna(row['holdings_json'])) else '{}')
        holdings = json.loads(holdings_raw) if holdings_raw and holdings_raw != '{}' else {}

        if not holdings:
            cash_val = float(row['target_cash']) if (row is not None and 'target_cash' in row and not pd.isna(row['target_cash'])) else (float(row['cash']) if (row is not None and 'cash' in row and not pd.isna(row['cash'])) else 10000.0)
            records.append({
                "Universe": universe_type,
                "Persona": persona_display,
                "Asset / Ticker": "CASH / ALL TICKERS",
                "Model Signal": "HOLD (CAPITAL PROTECTION)",
                "Win Prob P(UP)": "N/A",
                "Staged Target Allocation": f"${cash_val:,.2f} (100% Cash)",
                "Action": "HOLD CASH (NO TRADES)"
            })
        else:
            holdings = json.loads(row['target_holdings_json'])
            for asset, details in holdings.items():
                val = float(details.get('dollars', 0.0)) if isinstance(details, dict) else float(details)
                units = details.get('units', 0) if isinstance(details, dict) else 0
                
                prob_str = "N/A"
                rec_str = "BUY / ALLOCATE"
                if not df_scorecards.empty:
                    sc_match = df_scorecards[(df_scorecards['ticker'] == asset) & (df_scorecards['persona'] == persona_display)]
                    if not sc_match.empty:
                        prob_val = float(sc_match.iloc[0]['prob'])
                        prob_str = f"{prob_val:.1%}"
                        rec_str = str(sc_match.iloc[0]['recommendation']).upper()

                records.append({
                    "Universe": universe_type,
                    "Persona": persona_display,
                    "Asset / Ticker": asset,
                    "Model Signal": rec_str,
                    "Win Prob P(UP)": prob_str,
                    "Staged Target Allocation": f"${val:,.2f} ({units} shares)",
                    "Action": f"STAGED BUY (${val:,.2f})"
                })

    df_out = pd.DataFrame(records)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(df_out.to_string(index=False))
    print("==========================================================================================================================")

if __name__ == "__main__":
    generate_db_execution_table()
