import os
import pandas as pd
import numpy as np

tnx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'TNX_Test_Scorecard.xlsx')

try:
    tnx_excel = pd.ExcelFile(tnx_path)
    tnx_results = []
    
    for sheet in tnx_excel.sheet_names:
        df_sheet = pd.read_excel(tnx_excel, sheet_name=sheet, skiprows=2)
        if not df_sheet.empty:
            last_row = df_sheet.iloc[-1]
            tnx_results.append({
                'Ticker': sheet,
                'Ghost_UP': last_row.get('Bayesian Probability P(UP)', np.nan),
                'Ghost_Signal': last_row.get('model predicted direction daily return', 'UNKNOWN'),
                'Ghost_Conf': "YES" if last_row.get('Kelly Optimal Allocation %', 0) > 0 else "NO"
            })
            
    df_tnx = pd.DataFrame(tnx_results)
    
    print("=== MEGA-MACRO GHOST RUN PREDICTIONS (FOR ACTIVE PORTFOLIO) ===")
    print(f"{'Ticker':<10} | {'Ghost Signal':<15} | {'Ghost UP%':<15} | {'High Conf?':<15}")
    print("-" * 65)
    
    for _, row in df_tnx.iterrows():
        t = row['Ticker']
        sig_ghost = row.get('Ghost_Signal', 'N/A')
        up_ghost = row.get('Ghost_UP', np.nan)
        conf_ghost = row.get('Ghost_Conf', 'NO')
        
        up_ghost_str = f"{up_ghost:.1%}" if pd.notna(up_ghost) else "N/A"
        
        print(f"{t:<10} | {sig_ghost:<15} | {up_ghost_str:<15} | {conf_ghost:<15}")

except Exception as e:
    import traceback
    traceback.print_exc()
