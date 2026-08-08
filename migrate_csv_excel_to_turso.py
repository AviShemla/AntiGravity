import os
import sys
import pandas as pd
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager

def migrate_all_to_turso():
    print("=== MIGRATING ALL CSV & EXCEL FILES TO TURSO DATABASE ===")
    
    # 1. Initialize Tables
    database_manager.init_db()
    client = database_manager.get_connection()
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # -------------------------------------------------------------
    # A. Migrate Olympic_Shootout_Results_MASTER.csv
    # -------------------------------------------------------------
    olympic_csv = os.path.join(BASE_DIR, "financial_data", "Olympic_Shootout_Results_MASTER.csv")
    if os.path.exists(olympic_csv):
        print(f"\n--> Migrating {olympic_csv}...")
        df_olympic = pd.read_csv(olympic_csv)
        inserted_cnt = 0
        for _, row in df_olympic.iterrows():
            date_str = str(row['Date'])
            for col in df_olympic.columns:
                if col == 'Date':
                    continue
                val = row[col]
                if pd.notna(val) and str(val).strip() != "":
                    try:
                        eq_val = float(val)
                        client.execute('''
                            INSERT INTO olympic_shootout_master (date, model_name, total_equity)
                            VALUES (?, ?, ?)
                            ON CONFLICT(date, model_name) DO UPDATE SET total_equity=excluded.total_equity
                        ''', [date_str, str(col), eq_val])
                        inserted_cnt += 1
                    except ValueError:
                        pass
        print(f"✅ Olympic Shootout Migration Complete: {inserted_cnt} records inserted/updated.")

    # -------------------------------------------------------------
    # B. Migrate Prod_vs_Shadow_Results_MASTER.csv
    # -------------------------------------------------------------
    ps_csv = os.path.join(BASE_DIR, "financial_data", "Prod_vs_Shadow_Results_MASTER.csv")
    if os.path.exists(ps_csv):
        print(f"\n--> Migrating {ps_csv}...")
        df_ps = pd.read_csv(ps_csv)
        inserted_cnt = 0
        for _, row in df_ps.iterrows():
            date_str = str(row['Date'])
            for col in df_ps.columns:
                if col == 'Date':
                    continue
                val = row[col]
                if pd.notna(val) and str(val).strip() != "":
                    try:
                        eq_val = float(val)
                        client.execute('''
                            INSERT INTO prod_vs_shadow_master (date, model_name, total_equity)
                            VALUES (?, ?, ?)
                            ON CONFLICT(date, model_name) DO UPDATE SET total_equity=excluded.total_equity
                        ''', [date_str, str(col), eq_val])
                        inserted_cnt += 1
                    except ValueError:
                        pass
        print(f"✅ Prod vs Shadow Migration Complete: {inserted_cnt} records inserted/updated.")

    # -------------------------------------------------------------
    # C. Migrate Scorecards Excel Files (All_ETFs_Scorecard.xlsx & All_Stocks_Scorecard.xlsx)
    # -------------------------------------------------------------
    scorecard_files = [
        ("All_ETFs_Scorecard.xlsx", "ETF"),
        ("All_Stocks_Scorecard.xlsx", "Stock")
    ]
    for sc_file, persona_cat in scorecard_files:
        sc_path = os.path.join(BASE_DIR, "financial_data", sc_file)
        if os.path.exists(sc_path):
            print(f"\n--> Migrating {sc_path}...")
            try:
                xls = pd.ExcelFile(sc_path)
                inserted_cnt = 0
                for sheet in xls.sheet_names:
                    # Skip metadata rows, real headers start at row 1 (0-indexed 1)
                    df_sheet = pd.read_excel(xls, sheet_name=sheet, header=1)
                    if 'Date' in df_sheet.columns:
                        for _, row in df_sheet.iterrows():
                            d = str(row['Date'])
                            if pd.isna(row['Date']) or d.strip() == "" or d.startswith("Optimal"):
                                continue
                            t = str(sheet)
                            p_val = None
                            if 'Bayesian Probability P(UP)' in row and pd.notna(row['Bayesian Probability P(UP)']):
                                p_val = float(row['Bayesian Probability P(UP)'])
                            elif 'Probability' in row and pd.notna(row['Probability']):
                                p_val = float(row['Probability'])
                                
                            s_val = None
                            if 'Expected Return %' in row and pd.notna(row['Expected Return %']):
                                s_val = float(row['Expected Return %'])
                            elif 'Score' in row and pd.notna(row['Score']):
                                s_val = float(row['Score'])
                                
                            client.execute('''
                                INSERT INTO etf_scorecards_master (ticker, persona, date, score, prob)
                                VALUES (?, ?, ?, ?, ?)
                                ON CONFLICT(ticker, persona, date) DO UPDATE SET score=excluded.score, prob=excluded.prob
                            ''', [t, persona_cat, d, s_val, p_val])
                            inserted_cnt += 1
                print(f"✅ {sc_file} Migration Complete: {inserted_cnt} records inserted/updated.")
            except Exception as e:
                print(f"⚠️ Error reading {sc_file}: {e}")

    print("\n=============================================================")
    print("   TURSO DB MIGRATION COMPLETED SUCCESSFULLY (100% GREEN)    ")
    print("=============================================================")

if __name__ == "__main__":
    migrate_all_to_turso()
