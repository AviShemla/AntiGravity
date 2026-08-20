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
                if isinstance(cell, dict):
                    row_vals.append(cell.get('value') if cell.get('type') != 'null' else None)
                else:
                    row_vals.append(cell)
            rows.append(row_vals)
        return pd.DataFrame(rows, columns=cols)

import argparse

def generate_db_execution_table(target_date=None):
    print("==========================================================================================================================")
    date_str_hdr = f"FOR DATE: {target_date}" if target_date else "LATEST STAGED & LIVE SESSION"
    print(f"=== TURSO DB 100% BACKED PREDICTION & ALLOCATION BREAKDOWN ({date_str_hdr}) ===")
    print("==========================================================================================================================")

    # 1. Dynamically query pending_orders for Staged Holdings across all 8 personas
    if target_date:
        df_pending = query_turso(f"SELECT persona, date, target_cash, target_holdings_json FROM pending_orders WHERE date LIKE '{target_date}%'")
        df_scorecards = query_turso(f"SELECT ticker, persona, date, prob, expected_return, recommendation, kelly_allocation FROM etf_scorecards_master WHERE date LIKE '{target_date}%' ORDER BY persona, prob DESC")
        df_ledgers = query_turso(f"SELECT persona, date, cash, total_equity, holdings_json FROM capital_ledgers WHERE date LIKE '{target_date}%'")
    else:
        df_pending = query_turso("SELECT persona, date, target_cash, target_holdings_json FROM pending_orders")
        try:
            df_scorecards = query_turso("SELECT ticker, persona, date, prob, expected_return, recommendation, kelly_allocation FROM etf_scorecards_master ORDER BY date DESC, prob DESC")
        except:
            df_scorecards = pd.DataFrame()
        df_ledgers = query_turso("SELECT persona, date, cash, total_equity, holdings_json FROM capital_ledgers WHERE date = (SELECT MAX(date) FROM capital_ledgers)")

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

    ledger_dict = {}
    if not df_ledgers.empty:
        for _, r in df_ledgers.iterrows():
            ledger_dict[r['persona']] = r

    for universe_type, p_key in all_personas:
        row = pending_dict.get(p_key)
        if row is None or pd.isna(row['target_holdings_json']) or not row['target_holdings_json']:
            row = ledger_dict.get(p_key)

        persona_display = p_key.replace("ETF_", "")
        
        holdings_raw = '{}'
        if row is not None:
            if hasattr(row, '__getitem__') and 'target_holdings_json' in row and not pd.isna(row['target_holdings_json']):
                holdings_raw = row['target_holdings_json']
            elif hasattr(row, '__getitem__') and 'holdings_json' in row and not pd.isna(row['holdings_json']):
                holdings_raw = row['holdings_json']

        holdings = json.loads(holdings_raw) if holdings_raw and holdings_raw != '{}' else {}

        if not holdings:
            cash_val = float(row['target_cash']) if (row is not None and 'target_cash' in row and not pd.isna(row['target_cash'])) else (float(row['cash']) if (row is not None and 'cash' in row and not pd.isna(row['cash'])) else 10000.0)
            records.append({
                "Universe": universe_type,
                "Persona": persona_display,
                "Asset / Ticker": "CASH / ALL TICKERS",
                "Model Signal": "HOLD (CAPITAL PROTECTION)",
                "Win Prob P(UP)": "100.0% (Risk-Free)",
                "Staged Target Allocation": f"${cash_val:,.2f} (100% Cash)",
                "Action": "HOLD CASH (NO TRADES)"
            })
        else:
            for asset, details in holdings.items():
                val = float(details.get('dollars', 0.0)) if isinstance(details, dict) else float(details)
                units = details.get('units', 0) if isinstance(details, dict) else 0
                
                prob_str = "N/A"
                rec_str = "BUY / ALLOCATE"
                if not df_scorecards.empty:
                    sc_match = df_scorecards[(df_scorecards['ticker'] == asset) & (df_scorecards['persona'] == persona_display)]
                    if sc_match.empty:
                        sc_match = df_scorecards[df_scorecards['ticker'] == asset]
                        
                    if not sc_match.empty:
                        sc_row = sc_match.sort_values('date', ascending=False).iloc[0]
                        if sc_row['prob'] is not None:
                            prob_val = float(sc_row['prob'])
                            prob_str = f"{prob_val:.1%}"
                        if sc_row['recommendation'] is not None:
                            rec_str = str(sc_row['recommendation']).upper()

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
    parser = argparse.ArgumentParser(description="100% Turso DB Backed Intraday Execution & Prediction Audit Table")
    parser.add_argument("--date", type=str, help="Optional target date (YYYY-MM-DD). If omitted, queries MAX(date) dynamically.")
    args = parser.parse_args()
    generate_db_execution_table(target_date=args.date)
