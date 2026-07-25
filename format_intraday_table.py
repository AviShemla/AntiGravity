import pandas as pd
import json
import database_manager as dbm

pending_df = dbm.execute_query("SELECT persona, date, target_holdings_json FROM pending_orders")
ledgers_df = dbm.execute_query("SELECT persona, date, intraday_status, daily_pnl_json FROM capital_ledgers WHERE date = '2026-07-23'")

personas = ["Conservative", "Neutral", "Dynamic", "BallsForBrains", "ETF_Conservative", "ETF_Neutral", "ETF_Dynamic", "ETF_BallsForBrains"]

print("| Persona (Asset Class) | AI Recommendation (Pending Orders) | Intraday Sniper Execution Status | Intraday Trend (Live PnL) |")
print("|---|---|---|---|")

for p in personas:
    rec = "HOLD (No Action)"
    status = "Pending / No Trade"
    pnl = "$0.00"
    
    # Check pending
    if not pending_df.empty:
        p_row = pending_df[pending_df['persona'] == p]
        if not p_row.empty:
            th_str = p_row.iloc[0]['target_holdings_json']
            try:
                th = json.loads(th_str) if th_str else {}
                if th:
                    tickers = list(th.keys())
                    rec = f"BUY {', '.join(tickers)}"
            except: pass
    
    # Check ledgers
    if not ledgers_df.empty:
        l_row = ledgers_df[ledgers_df['persona'] == p]
        if not l_row.empty:
            status = l_row.iloc[0]['intraday_status']
            dpnl_str = l_row.iloc[0]['daily_pnl_json']
            try:
                dpnl = json.loads(dpnl_str) if dpnl_str else {}
                if dpnl:
                    total_pnl = sum(float(v) for v in dpnl.values())
                    pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
                    pnl = f"{pnl_str} ({', '.join(f'{k}: {v}' for k, v in dpnl.items())})"
            except: pass
            
    print(f"| {p} | {rec} | {status} | {pnl} |")
