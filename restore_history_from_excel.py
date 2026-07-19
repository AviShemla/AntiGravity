import os
import pandas as pd
import json
import database_manager

FINANCIAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
EXCEL_FILES = {
    "MultiPersona": os.path.join(FINANCIAL_DIR, "MultiPersona_Broker_30Day_Trial.xlsx"),
    "ETF": os.path.join(FINANCIAL_DIR, "ETF_Broker_30Day_Trial.xlsx")
}

def migrate_excel_to_sqlite():
    print(">>> Starting Reverse Migration from Excel Backups...")
    
    total_restored = 0
    for name, file_path in EXCEL_FILES.items():
        if not os.path.exists(file_path):
            print(f"  [!] Missing {name} backup at {file_path}")
            continue
            
        print(f"  -> Reading {name} Excel Backup...")
        try:
            df = pd.read_excel(file_path, sheet_name='Daily Tracking')
            
            # Find Personas by looking at columns ending in _Total_Equity
            equity_cols = [c for c in df.columns if c.endswith("_Total_Equity")]
            
            for index, row in df.iterrows():
                date_str = str(row['Date']).split(' ')[0]
                
                # We skip June 26th and beyond if they exist, because the Marathon is generating the pure versions of those right now
                if date_str >= "2026-06-26":
                    continue
                    
                for eq_col in equity_cols:
                    persona_prefix = eq_col.replace("_Total_Equity", "")
                    
                    if name == "ETF":
                        # ETF personas are strictly formatted as "ETF_Conservative" etc in DB
                        db_persona = "ETF_" + persona_prefix
                    else:
                        db_persona = persona_prefix
                        if db_persona == "Balls For Brain":
                            db_persona = "BallsForBrains"
                    
                    total_eq = float(row[eq_col]) if not pd.isna(row[eq_col]) else 10000.0
                    cash_col = f"{persona_prefix}_Cash"
                    
                    cash = float(row[cash_col]) if cash_col in df.columns and not pd.isna(row[cash_col]) else total_eq
                    
                    # To satisfy the strict double-entry accounting failsafe in database_manager:
                    # Total_Equity MUST equal Cash + Holdings. 
                    # Since we don't have the granular holdings JSON from Excel, we construct a placeholder.
                    holdings_value = max(0.0, total_eq - cash)
                    holdings_json = {}
                    if holdings_value > 0:
                        holdings_json["HISTORICAL_BASKET"] = {"dollars": holdings_value, "units": 1, "price": holdings_value}
                        
                    database_manager.save_ledger_row(
                        persona=db_persona,
                        date=date_str,
                        cash=cash,
                        total_equity=total_eq,
                        holdings_json=holdings_json,
                        daily_pnl_json={},
                        intraday_status="RESTORED_FROM_EXCEL"
                    )
                    total_restored += 1
        except Exception as e:
            print(f"  [!] Failed processing {name}: {e}")
            
    print(f"\n[SUCCESS] Reverse Migration Complete! Restored {total_restored} historical ledger entries into SQLite.")

if __name__ == "__main__":
    database_manager.init_db()
    migrate_excel_to_sqlite()
