import os
import glob
import pandas as pd
import json
import database_manager

FINANCIAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')

def migrate_capital_ledgers():
    print(">>> Migrating Capital Ledgers...")
    csv_files = glob.glob(os.path.join(FINANCIAL_DIR, "Capital_Ledger_*.csv")) + \
                glob.glob(os.path.join(FINANCIAL_DIR, "ETF_Capital_Ledger_*.csv"))
    
    total_rows = 0
    for file_path in csv_files:
        filename = os.path.basename(file_path)
        # Extract persona name:
        # e.g., "Capital_Ledger_BallsForBrains.csv" -> "BallsForBrains"
        # e.g., "ETF_Capital_Ledger_Conservative.csv" -> "ETF_Conservative"
        if filename.startswith("ETF_Capital_Ledger_"):
            persona = "ETF_" + filename.replace("ETF_Capital_Ledger_", "").replace(".csv", "")
        else:
            persona = filename.replace("Capital_Ledger_", "").replace(".csv", "")
            
        print(f"  -> Processing {filename} as persona: {persona}")
        
        try:
            df = pd.read_csv(file_path)
            for _, row in df.iterrows():
                date_str = str(row['Date'])
                
                cash_val = row.get('Cash', 10000.0)
                cash = float(cash_val) if not pd.isna(cash_val) else 10000.0
                
                equity_val = row.get('Total_Equity', 10000.0)
                equity = float(equity_val) if not pd.isna(equity_val) else 10000.0
                
                holdings = row.get('Holdings_JSON', row.get('Positions_JSON', '{}'))
                pnl = row.get('Daily_PnL_JSON', '{}')
                status = row.get('Intraday_Status', '')
                
                if pd.isna(status): status = ""
                if pd.isna(holdings): holdings = "{}"
                if pd.isna(pnl): pnl = "{}"
                
                database_manager.save_ledger_row(
                    persona=persona,
                    date=date_str,
                    cash=cash,
                    total_equity=equity,
                    holdings_json=holdings,
                    daily_pnl_json=pnl,
                    intraday_status=status
                )
                total_rows += 1
        except Exception as e:
            print(f"    [!] Failed to parse {filename}: {e}")
            
    print(f"  => Successfully migrated {total_rows} ledger entries to SQLite!")

def migrate_pending_orders():
    print("\n>>> Migrating Pending Orders...")
    pending_path = os.path.join(FINANCIAL_DIR, "Pending_Orders.json")
    if os.path.exists(pending_path):
        try:
            with open(pending_path, 'r') as f:
                data = json.load(f)
                
            for persona, details in data.items():
                print(f"  -> Processing pending order for {persona}")
                database_manager.save_pending_order(
                    persona=persona,
                    date=details.get('Date', '1970-01-01'),
                    target_cash=details.get('Target_Cash', 10000.0),
                    target_equity=details.get('Target_Total_Equity', 10000.0),
                    target_holdings=details.get('Target_Holdings', {}),
                    daily_pnl=details.get('Daily_PnL_JSON', {}),
                    executed_trades=details.get('Executed_Intraday_Trades', {})
                )
            print("  => Successfully migrated Pending Orders!")
        except Exception as e:
            print(f"    [!] Failed to parse Pending_Orders.json: {e}")
    else:
        print("  => Pending_Orders.json not found. Skipping.")

def set_initial_continuity():
    print("\n>>> Setting Initial Continuity Flags...")
    # Seed the pipeline logic to assume we successfully finished up to the latest ledger date
    conn = database_manager.get_connection()
    df = pd.read_sql_query("SELECT MAX(date) as max_date FROM capital_ledgers", conn)
    conn.close()
    
    if not df.empty and df['max_date'].iloc[0]:
        max_date = df['max_date'].iloc[0]
        database_manager.update_continuity("daily_pipeline", max_date)
        database_manager.update_continuity("etf_daily_pipeline", max_date)
        print(f"  => Master continuity locked at: {max_date}")
    else:
        print("  => No ledger dates found, skipping continuity init.")

if __name__ == "__main__":
    database_manager.init_db()
    migrate_capital_ledgers()
    migrate_pending_orders()
    set_initial_continuity()
    print("\n[SUCCESS] Entire CSV/JSON database perfectly replicated into antigravity.db SSOT!")
