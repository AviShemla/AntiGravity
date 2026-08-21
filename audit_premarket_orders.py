import os
import sys
import json
import urllib.request
from dotenv import load_dotenv

sys.path.insert(0, r"C:\Users\AviShemla\AntiGravity")
load_dotenv(os.path.join(r"C:\Users\AviShemla\AntiGravity", ".env"))

import database_manager

def run_premarket_audit(target_date=None):
    print("==========================================================================", flush=True)
    print("=== PERMANENT PRE-MARKET AUDIT TOOL (8 PERSONAS) ===", flush=True)
    print("==========================================================================", flush=True)

    url = "https://theoracle-avishe.aws-eu-west-1.turso.io/v2/pipeline"
    token = os.environ.get("TURSO_AUTH_TOKEN")

    if not token:
        print("[ERROR] TURSO_AUTH_TOKEN missing from environment!")
        return

    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": "SELECT persona, date, target_cash, target_total_equity, target_holdings_json FROM pending_orders"}}
        ]
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })

    pending_map = {}
    try:
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            item = res['results'][0]
            if item['type'] != 'error':
                result = item['response']['result']
                cols = [c['name'] for c in result['cols']]
                rows = result['rows']
                for row in rows:
                    vals = [v.get('value') for v in row]
                    rd = dict(zip(cols, vals))
                    pending_map[rd['persona']] = rd
    except Exception as e:
        print(f"[ERROR] Failed to fetch pending_orders: {e}")
        return

    personas = [
        ('Single Stock', 'Conservative'),
        ('Single Stock', 'Neutral'),
        ('Single Stock', 'BallsForBrains'),
        ('Single Stock', 'Dynamic'),
        ('Multi-Sector ETF', 'ETF_Conservative'),
        ('Multi-Sector ETF', 'ETF_Neutral'),
        ('Multi-Sector ETF', 'ETF_BallsForBrains'),
        ('Multi-Sector ETF', 'ETF_Dynamic')
    ]

    for cat, p_name in personas:
        p_data = pending_map.get(p_name)
        print(f"\n[{cat.upper()}] {p_name}")
        if not p_data:
            print("   Status: NO PENDING ORDERS STAGED")
            continue

        p_date = str(p_data.get('date'))[:10]
        if target_date and p_date != target_date:
            print(f"   Status: ⚠️ PENDING DATE MISMATCH ({p_date} vs target {target_date})")
            continue

        t_cash = float(p_data.get('target_cash', 0.0))
        t_eq = float(p_data.get('target_total_equity', 0.0))
        t_holdings = json.loads(p_data.get('target_holdings_json', '{}'))

        # Fetch last settled holdings via raw Turso HTTP
        stmt_sql = f"SELECT date, Holdings_JSON FROM daily_holdings WHERE persona='{p_name}' ORDER BY date DESC LIMIT 1"
        payload_h = {"requests": [{"type": "execute", "stmt": {"sql": stmt_sql}}]}
        req_h = urllib.request.Request(url, data=json.dumps(payload_h).encode('utf-8'), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        last_holdings = {}
        try:
            with urllib.request.urlopen(req_h) as resp_h:
                res_h = json.loads(resp_h.read().decode('utf-8'))
                rows_h = res_h['results'][0]['response']['result']['rows']
                if rows_h:
                    last_holdings = json.loads(rows_h[0][1]['value'])
        except Exception as e_h:
            pass

        print(f"   Staged Date: {p_date} | Target Cash: ${t_cash:,.2f} | Target Equity: ${t_eq:,.2f}")
        print("   Exact Trade Orders (Deltas):")

        # Check Target vs Last
        all_tickers = set(list(t_holdings.keys()) + list(last_holdings.keys()))
        all_tickers.discard('Cash')

        for ticker in sorted(all_tickers):
            t_info = t_holdings.get(ticker, {})
            l_info = last_holdings.get(ticker, {})

            t_val = float(t_info.get('dollars', 0.0)) if isinstance(t_info, dict) else float(t_info)
            l_val = float(l_info.get('dollars', 0.0)) if isinstance(l_info, dict) else float(l_info)

            delta = t_val - l_val

            if l_val <= 1.0 and t_val > 1.0:
                action = f"BUY  (New Position: ${t_val:,.2f})"
            elif l_val > 1.0 and t_val <= 1.0:
                action = f"SELL (Exit Position: Previous ${l_val:,.2f})"
            elif l_val > 1.0 and t_val > 1.0:
                if abs(delta) > 5.0:
                    sign = "+" if delta > 0 else "-"
                    action = f"REBALANCE ({sign}${abs(delta):,.2f} -> New Target: ${t_val:,.2f})"
                else:
                    action = f"HOLD (Unchanged ${t_val:,.2f})"
            else:
                continue

            print(f"     - {ticker:<6}: {action}")

    print("\n==========================================================================")
    os._exit(0)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Permanent Reusable Pre-Market Audit Tool")
    parser.add_argument("--date", type=str, default=None, help="Optional target date filter (e.g. 2026-08-18)")
    args = parser.parse_args()
    run_premarket_audit(args.date)
