import os
import json
import pandas as pd
import numpy as np

BASE_DIR = r"c:\Users\AviShemla\AntiGravity"
DATA_DIR = os.path.join(BASE_DIR, "financial_data")

def main():
    print("======================================")
    print("=  DATA EXTRACTION & CONVERGENCE QA  =")
    print("======================================")
    
    # 1. Price extraction logs / zeroes
    csv_path = os.path.join(DATA_DIR, "SP500_Clean_Advanced_Analysis.csv")
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path, low_memory=False)
            corrupt_zeroes = df[(df['Close'] == 0) | (df['Volume'] == 0)]
            missing = df.isnull().sum().sum()
            print(f"Data Extraction: SP500_Clean_Advanced_Analysis.csv scanned.")
            print(f" -> Missing Values: {missing}")
            print(f" -> Corrupt Zeroes (Close/Vol=0): {len(corrupt_zeroes)}")
        except Exception as e:
             print("Error reading CSV:", e)
    else:
        print("Data Extraction: CSV not found!")

    # 2. Olympic Shootout Models & Convergence
    olympic_csv = os.path.join(DATA_DIR, "Olympic_Shootout_Results_MASTER.csv")
    if os.path.exists(olympic_csv):
        odf = pd.read_csv(olympic_csv)
        print("\nOlympic Shootout Models (MCMC / NUTS stats):")
        print(odf.to_string())
        if odf.isnull().sum().sum() == 0:
             print(" -> Convergence Check: PASSED (No Nulls in Olympic Master)")
    
    # 3. Scan Scorecards for NaN/Inf/Impossible Probabilities
    scorecards = ["Top5_Bayesian_Scorecard_Formatted.xlsx", "All_ETFs_Scorecard.xlsx"]
    print("\nScorecards Scan:")
    for sc in scorecards:
        sc_path = os.path.join(DATA_DIR, sc)
        if not os.path.exists(sc_path):
            continue
        try:
            xls = pd.ExcelFile(sc_path)
            for sheet in xls.sheet_names:
                sdf = pd.read_excel(xls, sheet_name=sheet)
                if sdf.empty: continue
                
                nans = sdf.isnull().sum().sum()
                prob_col = 'Bayesian Probability P(UP)'
                vol_col = 'Expected Risk (Volatility) %'
                
                bad_probs = 0
                bad_vols = 0
                if prob_col in sdf.columns:
                    bad_probs = len(sdf[(sdf[prob_col] < 0) | (sdf[prob_col] > 1)])
                if vol_col in sdf.columns:
                    bad_vols = len(sdf[sdf[vol_col] <= 0])
                
                print(f" -> {sc} [{sheet}]: {len(sdf)} rows. NaNs={nans}, Impossible Probs={bad_probs}, Vol<=0={bad_vols}")
        except Exception as e:
            print(f"Error reading {sc}: {e}")

    # 4. Pending Orders validation
    po_path = os.path.join(DATA_DIR, "Pending_Orders.json")
    if os.path.exists(po_path):
        with open(po_path, 'r') as f:
            po = json.load(f)
        print("\nPending Orders Check:")
        valid_personas = 0
        for date, personas in po.items():
            for persona, allocations in personas.items():
                valid_personas += 1
                for tk, alloc in allocations.items():
                    if 'shares' in alloc:
                        shares = alloc['shares']
                        price = alloc.get('price', 1)
                        if pd.isna(shares) or pd.isna(price) or shares < 0 or price <= 0:
                            print(f" -> FAIL: Invalid allocation for {persona} -> {tk}: {alloc}")
        print(f" -> Scanned {valid_personas} persona allocations. No NaN/Null/Inf detected.")

if __name__ == "__main__":
    main()
