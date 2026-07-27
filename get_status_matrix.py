import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager
import json

def get_latest_status():
    personas = [
        "Single_Stocks_Conservative", 
        "Single_Stocks_Neutral", 
        "Single_Stocks_Dynamic", 
        "Single_Stocks_BallsForBrains",
        "ETF_Conservative", 
        "ETF_Neutral", 
        "ETF_Dynamic", 
        "ETF_BallsForBrains"
    ]
    
    for p in personas:
        # Get pending orders
        query_orders = f"SELECT ai_recommendation, target_date FROM pending_orders WHERE persona = '{p}' ORDER BY target_date DESC LIMIT 1"
        res_orders = database_manager.execute_query(query_orders)
        rec = "None"
        t_date = "N/A"
        if res_orders:
            rec = res_orders[0][0]
            t_date = res_orders[0][1]
            
        # Get sniper status from ledgers
        query_ledger = f"SELECT intraday_status, daily_pnl_json FROM capital_ledgers WHERE persona = '{p}' ORDER BY date DESC LIMIT 1"
        res_ledger = database_manager.execute_query(query_ledger)
        sniper = "WAITING FOR MONDAY OPEN"
        pnl = "$0.00"
        if res_ledger:
            # If intraday status exists, use it. But since it's the weekend, we expect waiting.
            if res_ledger[0][0]:
                sniper = res_ledger[0][0]
                
        print(f"| {p} | {rec} (Date: {t_date}) | {sniper} | {pnl} |")

if __name__ == '__main__':
    get_latest_status()
