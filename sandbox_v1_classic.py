import os
import sys
import json
import subprocess
import pandas as pd
try:
    import pandas_market_calendars as mcal
except ImportError:
    mcal = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "financial_data")
python_exe = sys.executable

def get_target_date():
    if mcal is None:
        return pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d')
    nyse = mcal.get_calendar('NYSE')
    now = pd.Timestamp.now(tz='America/New_York')
    schedule = nyse.schedule(start_date=(now - pd.Timedelta(days=7)).strftime('%Y-%m-%d'), end_date=now.strftime('%Y-%m-%d'))
    past = schedule[schedule['market_close'] < now]
    if past.empty:
        return now.strftime('%Y-%m-%d')
    return past.iloc[-1].name.strftime('%Y-%m-%d')

def run_sandbox():
    print("\n==============================================")
    print("=== STARTING V1 CLASSIC SHADOW SANDBOX ===")
    print("==============================================\n")
    
    target_date = get_target_date()
    print(f"Target Date: {target_date}")
    
    # 1. Load VIP Stocks
    vip_file = os.path.join(DATA_DIR, "VIP_Tickers.json")
    vip_tickers = []
    if os.path.exists(vip_file):
        with open(vip_file, "r") as f:
            vip_data = json.load(f).get('sectors_dict', {})
            for sec, ticks in vip_data.items():
                vip_tickers.extend(ticks)
    vip_tickers = list(set(vip_tickers))
    
    # 2. Add Sector ETFs
    etf_tickers = ['XLK', 'XLF', 'XLV', 'XLE', 'XLY', 'XLP', 'XLU', 'XLI', 'XLB', 'XLC', 'XLRE']
    
    all_tickers = list(set(vip_tickers + etf_tickers))
    if not all_tickers:
        print("No tickers found to sandbox. Exiting.")
        return
        
    print(f"Loaded {len(vip_tickers)} VIP Stocks and {len(etf_tickers)} ETFs.")
    
    # 3. Call backtest_worker.py in parallel chunks
    import concurrent.futures
    import math
    
    num_cores = max(1, os.cpu_count() - 2)
    chunk_size = max(1, math.ceil(len(all_tickers) / num_cores))
    chunks = [all_tickers[i:i + chunk_size] for i in range(0, len(all_tickers), chunk_size)]
    
    def run_worker(chunk_index, chunk_tickers):
        chunk_json = os.path.join(DATA_DIR, f"Sandbox_V1_Classic_{target_date}_chunk{chunk_index}.json")
        tickers_csv = ",".join(chunk_tickers)
        cmd = [python_exe, os.path.join(BASE_DIR, "backtest_worker.py"), "--date", target_date, "--tickers", tickers_csv, "--out", chunk_json]
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Chunk {chunk_index} Failed: {e}")
        return chunk_json

    print(f"Spawning {len(chunks)} parallel PyMC Subprocesses for {len(all_tickers)} assets...")
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_cores) as executor:
        futures = [executor.submit(run_worker, i, chunk) for i, chunk in enumerate(chunks)]
        for future in concurrent.futures.as_completed(futures):
            chunk_json = future.result()
            if os.path.exists(chunk_json):
                with open(chunk_json, "r") as f:
                    chunk_data = json.load(f)
                    results.update(chunk_data)
                try:
                    os.remove(chunk_json)
                except:
                    pass

    # 4. Parse JSON and export CSV
    if results:
            
        records = []
        for ticker, data in results.items():
            records.append({
                'Date': target_date,
                'Ticker': ticker,
                'Asset_Type': 'ETF' if ticker in etf_tickers else 'Stock',
                'Bayesian_P(UP)': data.get('prob', 0),
                'Expected_Return': data.get('exp_ret', 0),
                'Expected_Volatility': data.get('exp_vol', 0)
            })
            
        df = pd.DataFrame(records)
        df = df.sort_values(by='Bayesian_P(UP)', ascending=False)
        out_csv = os.path.join(DATA_DIR, "Sandbox_V1_Classic_Scorecard.csv")
        df.to_csv(out_csv, index=False)
        
        print("\n=== SANDBOX EXECUTION COMPLETE ===")
        print(f"V1 Classic Scorecard exported to {out_csv}")
        
        try:
            os.remove(out_json)
        except:
            pass

if __name__ == '__main__':
    run_sandbox()
