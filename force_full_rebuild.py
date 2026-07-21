import os
import sys
import subprocess
import pandas as pd

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
python_exe = sys.executable

def run_cmd(cmd):
    print(f"\n---> RUNNING: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=BASE_DIR)
    if res.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
        sys.exit(1)

if __name__ == "__main__":
    target_date = '2026-07-20' # Data Date
    prediction_date = '2026-07-21' # Prediction Target Date
    
    print("=== FORCE FULL REBUILD TRIGGERED ===")
    
    print("\n--- 1. Single Stock Data Fetch ---")
    run_cmd([python_exe, "SPY.py"])
    
    print("\n--- 2. Single Stock Deep Learning Inference ---")
    run_cmd([python_exe, "daily_dl_inference.py"])
    
    print("\n--- 3. Single Stock Bayesian Scorecard ---")
    run_cmd([python_exe, "export_bayesian_scorecard_formatted.py", "--target-date", target_date])
    
    print("\n--- 4. Single Stock QA ---")
    run_cmd([python_exe, "qa_models.py"])
    
    print("\n--- 5. Single Stock Virtual Broker ---")
    run_cmd([python_exe, "virtual_broker.py", "--target-date", prediction_date])
    
    print("\n--- 6. ETF Pipeline (Dynamic Screener) ---")
    run_cmd([python_exe, "generate_dynamic_etfs.py"])
    
    print("\n--- 7. ETF Pipeline (Hybrid Matrix & Screener) ---")
    # Fetch target ETFs
    import json
    try:
        with open(os.path.join(BASE_DIR, 'financial_data', 'Dynamic_Target_ETFs.json'), 'r') as f:
            TARGET_ETFS = json.load(f)
    except:
        TARGET_ETFS = ['XLK']
        
    for etf in TARGET_ETFS:
        run_cmd([python_exe, "build_etf_hybrid_matrix.py", etf])
        run_cmd([python_exe, "run_etf_hybrid_screener.py", etf])
        run_cmd([python_exe, "export_etf_scorecard.py", etf, "--target-date", target_date])
        
    print("\n--- 8. ETF Scorecard Compilation ---")
    run_cmd([python_exe, "compile_etf_scorecards.py"])
    
    print("\n--- 9. ETF Virtual Broker ---")
    run_cmd([python_exe, "etf_virtual_broker.py", "--target-date", prediction_date])
    
    print("\n--- 10. Final Turso Export / Excel ---")
    run_cmd([python_exe, "export_broker_excel_report.py"])
    run_cmd([python_exe, "export_etf_broker_excel.py"])
    
    print("\n=== FULL PIPELINE REBUILD SUCCESSFUL ===")
    os._exit(0)
