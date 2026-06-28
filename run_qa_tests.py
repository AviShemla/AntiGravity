import pandas as pd
import numpy as np
import os
import json
import sys
import shutil
import datetime

workspace = r"C:\Users\AviShemla\AntiGravity"
os.chdir(workspace)
sys.path.insert(0, workspace)

results = []

def log(msg):
    print(msg)
    results.append(msg)

# Test 1: Virtual Broker
log("=== Test 1: Virtual Broker ===")
try:
    base_dir = os.path.join(workspace, 'financial_data')
    excel_path = os.path.join(base_dir, 'Top5_Bayesian_Scorecard_Formatted.xlsx')
    mock_excel_path = os.path.join(base_dir, 'Top5_Bayesian_Scorecard_Formatted_MOCK.xlsx')
    
    # 1. Generate mock
    xls = pd.ExcelFile(excel_path)
    sheets = {sheet: pd.read_excel(xls, sheet_name=sheet, skiprows=2) for sheet in xls.sheet_names}
    
    first_sheet_name = xls.sheet_names[0]
    second_sheet_name = xls.sheet_names[1]
    
    # Identify target_date (last row of first sheet originally)
    df_first = sheets[first_sheet_name]
    target_date = df_first.iloc[-1]['date'] if 'date' in df_first.columns else df_first.iloc[-1]['Date']
    target_date_str = pd.to_datetime(target_date).strftime('%Y-%m-%d')
    
    # 2. Delete target_date row from first sheet
    sheets[first_sheet_name] = sheets[first_sheet_name].iloc[:-1]
    
    # 3. Ensure it exists in second sheet
    df_second = sheets[second_sheet_name]
    second_date = df_second.iloc[-1]['date'] if 'date' in df_second.columns else df_second.iloc[-1]['Date']
    second_date_str = pd.to_datetime(second_date).strftime('%Y-%m-%d')
    
    # Write mock excel
    with pd.ExcelWriter(mock_excel_path) as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=2)
            # Re-inject the two title rows so the virtual broker's skiprows=2 doesn't skip actual data
            worksheet = writer.sheets[sheet_name]
            worksheet.write(0, 0, 'Model chosen: PyMC Dual-Head + Rust SV Engine')
            worksheet.write(1, 0, 'Predictors: MOCK')
            
    # Modify virtual_broker.py temporarily to use mock
    vb_path = os.path.join(workspace, 'virtual_broker.py')
    with open(vb_path, 'r') as f:
        vb_code = f.read()
    
    mock_vb_code = vb_code.replace("'Top5_Bayesian_Scorecard_Formatted.xlsx'", "'Top5_Bayesian_Scorecard_Formatted_MOCK.xlsx'")
    with open(vb_path, 'w') as f:
        f.write(mock_vb_code)
        
    # 4. Run virtual_broker.py
    # We will import it and run_virtual_broker, but wait, it uses sys.argv
    # Let's set sys.argv
    sys.argv = ['virtual_broker.py', '--target-date', second_date_str]
    
    import virtual_broker
    try:
        virtual_broker.run_virtual_broker()
        pending_orders_path = os.path.join(base_dir, 'Pending_Orders.json')
        if os.path.exists(pending_orders_path):
            with open(pending_orders_path, 'r') as f:
                po = json.load(f)
            log(f"Test 1 PASSED: Script completed and generated Pending_Orders.json. Date: {po.get('Date')}")
        else:
            log("Test 1 FAILED: Script did not crash but Pending_Orders.json missing.")
    except Exception as e:
        log(f"Test 1 FAILED: Fatal abort with error: {e}")
        
    # Restore virtual_broker.py
    with open(vb_path, 'w') as f:
        f.write(vb_code)
        
except Exception as e:
    log(f"Test 1 ERROR: {e}")


# Test 2: Intraday Tracker
log("\n=== Test 2: Intraday Tracker ===")
try:
    # 1. Create mock Pending_Orders.json
    base_dir = os.path.join(workspace, 'financial_data')
    po_path = os.path.join(base_dir, 'Pending_Orders.json')
    backup_po_path = os.path.join(base_dir, 'Pending_Orders_BACKUP.json')
    if os.path.exists(po_path):
        shutil.copy(po_path, backup_po_path)
        
    mock_po = {
        "Persona": "Neutral",
        "Date": "2026-06-12",  # Friday
        "Target_Cash": 5000.0,
        "Target_Total_Equity": 10000.0,
        "Target_Holdings": {"AAPL": {"dollars": 5000.0, "units": 20, "price": 250.0}},
        "Daily_PnL_JSON": {},
        "Executed_Intraday_Trades": {}
    }
    with open(po_path, 'w') as f:
        json.dump(mock_po, f)
        
    # We need to run intraday_tracker.py with --target-date 2026-06-12 (Friday)
    # Simulate today is Saturday or Sunday
    # The script uses datetime.datetime.now() ? Let's just run it with the argument.
    sys.argv = ['intraday_tracker.py', '--target-date', '2026-06-12']
    
    # We need to test if it swallows the tz error. We run it directly.
    import intraday_tracker
    try:
        # intraday_tracker usually runs logic in its __main__ or has a function
        # let's execute the script file since we modified sys.argv
        with open('intraday_tracker.py', 'r') as f:
            code = f.read()
            
        exec_namespace = {'__name__': '__main__'}
        exec(code, exec_namespace)
        
        # Check if it succeeded without aborting into cash
        # If it aborted into cash, the ledger would show Cash = Total_Equity and empty holdings
        import database_manager
        ledger = database_manager.get_ledger("Neutral")
        
        target_rows = ledger[ledger['Date'] == '2026-06-12']
        if not target_rows.empty:
            last_row = target_rows.iloc[-1]
            holdings = json.loads(last_row['Holdings_JSON'])
            if "AAPL" in holdings or (last_row['Cash'] < last_row['Total_Equity']):
                log("Test 2 PASSED: Successfully committed Friday trade without weekend abort.")
            else:
                log(f"Test 2 FAILED: Aborted into cash or didn't execute trade properly. Holdings: {holdings}, Cash: {last_row['Cash']}")
        else:
            log("Test 2 FAILED: Did not commit to ledger for 2026-06-12.")
            
    except Exception as e:
        log(f"Test 2 FAILED with error: {e}")
        
    # Restore
    if os.path.exists(backup_po_path):
        shutil.move(backup_po_path, po_path)
except Exception as e:
    log(f"Test 2 ERROR: {e}")

# Test 3: Marathon Engine
log("\n=== Test 3: Marathon Engine ===")
try:
    # We need to temporarily patch datetime.date.today() to return a Saturday
    # run_backtests.py uses `pd.bdate_range(end=today, periods=6)` or something.
    import run_backtests
    
    # Let's mock datetime
    class MockDate(datetime.date):
        @classmethod
        def today(cls):
            # Return a Saturday
            return datetime.date(2026, 6, 13)
            
    original_date = datetime.date
    datetime.date = MockDate
    import pandas as pd
    
    try:
        # Run the array generation logic.
        # run_backtests.py has `sim_dates` generated.
        # Let's execute run_backtests.py
        # Actually, let's just run it as it is
        sys.argv = ['run_backtests.py']
        with open('run_backtests.py', 'r') as f:
            code = f.read()
            
        # Instead of running the whole engine, let's extract the sim_dates logic
        # and test if Friday is included.
        # The script does: today = datetime.date.today()
        # sim_dates = pd.bdate_range(end=today, periods=6)[:-1]
        # Or something. Let's just find `sim_dates` after executing the top part
        # Let's run the whole file but limit it or just parse the output
        namespace = {}
        # We will parse the code for `sim_dates`
        exec(code, namespace)
        sim_dates = namespace.get('sim_dates', [])
        
        friday_str = '2026-06-12'
        has_friday = any(str(d)[:10] == friday_str for d in sim_dates)
        
        if has_friday:
            log(f"Test 3 PASSED: Friday ({friday_str}) is included in sim_dates. sim_dates: {[str(d)[:10] for d in sim_dates]}")
        else:
            log(f"Test 3 FAILED: Friday ({friday_str}) is MISSING from sim_dates. sim_dates: {[str(d)[:10] for d in sim_dates]}")
            
    except Exception as e:
        # if it runs the backtest it might take long. We can also just read the code to see if it fixes it.
        log(f"Test 3 RUN exception: {e}")
        
    datetime.date = original_date
except Exception as e:
    log(f"Test 3 ERROR: {e}")

with open('QA_Results.txt', 'w') as f:
    f.write('\n'.join(results))
