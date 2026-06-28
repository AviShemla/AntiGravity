import pandas as pd
import numpy as np
import yfinance as yf
import os
import json
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
os.makedirs(BASE_DIR, exist_ok=True)
OUT_PATH = os.path.join(BASE_DIR, 'Master_ETF_Universe.json')

# The untouchable 11 Core Sectors to guarantee baseline economic coverage
CORE_SECTORS = ["XLK", "XLV", "XLY", "XLF", "XLC", "XLI", "XLE", "XLP", "XLU", "XLRE", "XLB"]

def run_universe_screener():
    print("=========================================================")
    print("   AUTONOMOUS ETF UNIVERSE RECONSTRUCTION (SUNDAY RUN) ")
    print("=========================================================\n")
    
    # 1. ACQUIRE ALL US ETFs FROM NASDAQ FTP
    print("[1/5] Connecting to NASDAQ FTP to download Master Ticker Registry...")
    try:
        df = pd.read_csv('ftp://ftp.nasdaqtrader.com/symboldirectory/nasdaqtraded.txt', sep='|')
        all_etfs = df[df['ETF'] == 'Y']['Symbol'].dropna().tolist()
        all_etfs = [t for t in all_etfs if isinstance(t, str) and '$' not in t and '.' not in t]
        print(f"  -> Discovered {len(all_etfs)} Traded US ETFs.")
    except Exception as e:
        print(f"  [CRITICAL ERROR] Failed to hit NASDAQ FTP: {e}")
        return

    # 2. BULK VOLUME DOWNLOAD WITH COOLDOWN PROTECTION
    print("\n[2/5] Downloading 10-day market data with defensive cooldowns...")
    
    import time
    chunk_size = 100
    all_data_frames = []
    
    for i in range(0, len(all_etfs), chunk_size):
        chunk = all_etfs[i:i+chunk_size]
        print(f"  -> Downloading Chunk {i//chunk_size + 1}/{(len(all_etfs)//chunk_size) + 1} ({len(chunk)} ETFs)...")
        try:
            data = yf.download(chunk, period="10d", progress=False)
            if not data.empty and 'Volume' in data:
                all_data_frames.append(data)
        except Exception as e:
            print(f"  [WARNING] Chunk {i//chunk_size + 1} failed: {e}")
            
        time.sleep(10) # 10 SECOND COOLDOWN
        
    if not all_data_frames:
        print("  [ERROR] Completely failed to download Volume matrices.")
        return
        
    final_data = pd.concat(all_data_frames, axis=1)
    
    if 'Volume' not in final_data or 'Close' not in final_data:
        print("  [ERROR] yfinance failed to return Volume/Close matrices.")
        return
        
    vol_data = final_data['Volume']
    close_data = final_data['Close']

    # 3. APPLY $50M LIQUIDITY FIREWALL
    print("\n[3/5] Enforcing the $50,000,000 Daily Dollar Volume Firewall...")
    valid_thematics = []
    
    # Calculate avg volume and avg close
    avg_vol = vol_data.mean()
    avg_close = close_data.mean()
    
    # Dollar Volume = Avg Shares * Avg Price
    dollar_volume = avg_vol * avg_close
    
    # Filter highly liquid ETFs (>$50M / day)
    liquid_etfs = dollar_volume[dollar_volume >= 50000000].index.tolist()
    
    # Remove Core Sectors from the thematic pool so they don't get double counted
    thematic_pool = [t for t in liquid_etfs if t not in CORE_SECTORS]
    print(f"  -> {len(thematic_pool)} Thematic ETFs survived the institutional liquidity wipeout.")

    # 4. MOMENTUM / VOLATILITY SORTING (THE 24 SLOTS)
    print("\n[4/5] Hunting for 24 High-Octane Thematic ETFs (Momentum * Volatility)...")
    results = []
    for t in thematic_pool:
        series = close_data[t].dropna()
        if len(series) < 5: continue
        
        # We only have 10 days of data here, so we use short-term 10-day momentum
        mom = (series.iloc[-1] - series.iloc[0]) / series.iloc[0]
        daily_ret = series.pct_change().dropna()
        if daily_ret.empty: continue
        vol = daily_ret.std() * np.sqrt(252)
        
        results.append({
            "ETF": t,
            "Opportunity": mom * vol
        })
        
    df_results = pd.DataFrame(results).dropna()
    df_results = df_results.sort_values(by="Opportunity", ascending=False).reset_index(drop=True)
    
    top_24 = df_results.head(24)['ETF'].tolist()
    print("  -> Top Thematic Picks This Week:")
    for i, row in df_results.head(10).iterrows():
        print(f"     #{i+1}: {row['ETF'].ljust(5)} (Score: {row['Opportunity']:.4f})")

    # 5. MERGE AND DEPLOY
    print("\n[5/5] Synthesizing Final Master Universe (11 Core + 24 Thematic)...")
    master_universe = CORE_SECTORS + top_24
    
    with open(OUT_PATH, 'w') as f:
        json.dump(master_universe, f, indent=4)
        
    print(f"\nSUCCESSFULLY REBUILT MASTER UNIVERSE (35 ETFs)!")
    print(f"   -> Saved to: {OUT_PATH}")
    print("   -> The Daily Pipeline will automatically inherit this updated hunting ground on Monday.\n")

if __name__ == "__main__":
    run_universe_screener()
