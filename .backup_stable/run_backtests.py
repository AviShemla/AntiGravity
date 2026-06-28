import pandas as pd
import json
import subprocess
import time
import os
import yfinance as yf

def wait_for_pipeline():
    print("\n>>> Checking if live pipeline is currently running...")
    while True:
        try:
            result = subprocess.run('wmic process where "name=\'python.exe\' or name=\'pythonw.exe\'" get commandline', capture_output=True, text=True, shell=True)
            out = result.stdout.lower()
            if 'master_pipeline.py' in out or 'daily_pipeline.py' in out:
                print("Live pipeline is currently running! Waiting 15 minutes before checking again...")
                time.sleep(900) # Wait 15 minutes
            else:
                print("Live pipeline is clear. Proceeding with Olympic Shootout.")
                break
        except Exception as e:
            print(f"WMIC check failed: {e}. Proceeding cautiously...")
            break

wait_for_pipeline()

# Load the lists generated previously
print(">>> Loading VIP lists from generate_test_lists logic...")
import sys
# A quick inline script to just grab the top 5 per sector to keep it slightly faster (optional), 
# but let's just grab the whole thing. For the sake of the 20 hour backtest, we will use top 20 per sector.
# Since it's a shootout, a smaller subset is fine as long as they are equally sized.

def get_backtest_lists():
    import generate_test_lists
    return generate_test_lists.el_cap_list, generate_test_lists.el_volti_list

# We can parse the stdout of generate_test_lists or just recreate it simply here.
def generate_lists():
    import io, requests
    html = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers={'User-Agent': 'Mozilla/5.0'}).text
    sp500_df = pd.read_html(io.StringIO(html))[0]
    tickers = [t.replace('.', '-') for t in sp500_df['Symbol'].tolist()]
    sectors = sp500_df['GICS Sector'].tolist()
    ticker_sector_map = dict(zip(tickers, sectors))
    
    data = yf.download(tickers, period="3mo", group_by="ticker", auto_adjust=False, progress=False)
    results = []
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            if df.empty: continue
            df = df.dropna(subset=['Close', 'Volume'])
            if len(df) < 50: continue
            recent_df = df.tail(30)
            avg_liquidity = (recent_df['Close'] * recent_df['Volume']).mean()
            returns = df['Close'].pct_change().dropna()
            vol = returns.std()
            if vol > 0:
                results.append({'Ticker': t.replace('-', '.'), 'Sector': ticker_sector_map.get(t, "Unknown").replace(' ', '_'), 'Liquidity': avg_liquidity, 'Volatility': vol})
        except: pass
        
    df = pd.DataFrame(results)
    for sec in df['Sector'].unique():
        sec_mask = df['Sector'] == sec
        min_l, max_l = df.loc[sec_mask, 'Liquidity'].min(), df.loc[sec_mask, 'Liquidity'].max()
        df.loc[sec_mask, 'Norm_Cap'] = (df.loc[sec_mask, 'Liquidity'] - min_l) / (max_l - min_l) if max_l > min_l else 0
        min_v, max_v = df.loc[sec_mask, 'Volatility'].min(), df.loc[sec_mask, 'Volatility'].max()
        df.loc[sec_mask, 'Norm_Vol'] = 1 - ((df.loc[sec_mask, 'Volatility'] - min_v) / (max_v - min_v)) if max_v > min_v else 0
        
    df['EL_CAP_Score'] = (df['Norm_Cap'] * 0.70) + (df['Norm_Vol'] * 0.30)
    df['EL_VOLTI_Score'] = (df['Norm_Cap'] * 0.30) + (df['Norm_Vol'] * 0.70)
    
    el_cap, el_volti = [], []
    for sector, group in df.groupby('Sector'):
        # For the backtest, we take the top 15 from each sector to keep runtime around 10 hours.
        top_cap = group.sort_values('EL_CAP_Score', ascending=False).head(15)['Ticker'].tolist()
        top_vol = group.sort_values('EL_VOLTI_Score', ascending=False).head(15)['Ticker'].tolist()
        el_cap.extend(top_cap)
        el_volti.extend(top_vol)
    return list(set(el_cap)), list(set(el_volti))

el_cap_tickers, el_volti_tickers = generate_lists()
print(f"Loaded {len(el_cap_tickers)} tickers for EL_CAP, {len(el_volti_tickers)} for EL_VOLTI")

# We want 5 trading days back from today.
today = pd.to_datetime('today').normalize()
trading_days = pd.bdate_range(end=today, periods=6)
# Exclude the very last day because we can't score its "next day" return yet if tomorrow hasn't happened.
sim_dates = trading_days[:-1]

def run_simulation(test_name, tickers_list):
    print(f"\n=======================================================")
    print(f"STARTING 5-DAY SIMULATION: {test_name}")
    print(f"=======================================================\n")
    
    cash = 10000.0
    holdings = {} # ticker -> {'dollars': X, 'price': Y}
    ledger = []
    
    for i, date in enumerate(sim_dates):
        date_str = date.strftime('%Y-%m-%d')
        print(f"\n[{i+1}/{len(sim_dates)}] Simulating {date_str}...")
        
        # 1. Settle yesterday's holdings using today's open/close prices
        # To get the actual return, we fetch the next business day's return
        next_bday = trading_days[i+1]
        next_bday_str = next_bday.strftime('%Y-%m-%d')
        
        equity = cash
        if holdings:
            print(f"  Settling {len(holdings)} open positions on {next_bday_str}...")
            # We fetch price data for the next_bday
            held_tickers = list(holdings.keys())
            try:
                # download data for the settlement day
                hist = yf.download(held_tickers, start=date_str, end=next_bday + pd.Timedelta(days=1), progress=False)
                for t in held_tickers:
                    alloc = holdings[t]['dollars']
                    entry_price = holdings[t]['price']
                    
                    try:
                        if len(held_tickers) > 1:
                            closes = hist['Close'][t]
                        else:
                            closes = hist['Close']
                        
                        settle_price = closes.loc[next_bday_str] if next_bday_str in closes.index else closes.iloc[-1]
                        
                        ret = (settle_price - entry_price) / entry_price
                        pnl = alloc * ret
                        cash += (alloc + pnl)
                        equity += (alloc + pnl)
                        print(f"    {t} Return: {ret*100:.2f}% -> PnL: ${pnl:.2f}")
                    except Exception as e:
                        print(f"    {t} failed to settle ({e}). Assuming 0% return.")
                        cash += alloc
                        equity += alloc
            except Exception as e:
                print(f"  Warning: Failed to fetch settlement prices: {e}")
                for t in held_tickers: cash += holdings[t]['dollars']; equity += holdings[t]['dollars']
        
        holdings.clear()
        
        # 2. Spawn PyMC Worker to get predictions for `date_str`
        out_json = f"tmp_pred_{test_name}.json"
        tickers_csv = ",".join(tickers_list)
        
        cmd = ["py", "backtest_worker.py", "--date", date_str, "--tickers", tickers_csv, "--out", out_json]
        print(f"  Spawning Bayesian Subprocess (Memory Protection Active)...")
        subprocess.run(cmd)
        
        # 3. Read predictions and allocate
        if os.path.exists(out_json):
            with open(out_json, 'r') as f:
                preds = json.load(f)
                
            # Filter Buys (P > 0.5 for BallsForBrains)
            buys = {k: v for k, v in preds.items() if v['prob'] > 0.5 and v['exp_ret'] > 0}
            print(f"  Found {len(buys)} Buy signals.")
            
            # Fetch today's close prices for entry
            buy_tickers = list(buys.keys())
            if buy_tickers:
                try:
                    hist = yf.download(buy_tickers, start=date_str, end=next_bday, progress=False)
                    for t in buy_tickers:
                        prob = buys[t]['prob']
                        ret = buys[t]['exp_ret']
                        vol = buys[t]['exp_vol'] if buys[t]['exp_vol'] > 0 else 0.01
                        
                        # Kelly
                        kelly = prob - ((1 - prob) / (ret / vol))
                        kelly = max(0.0, min(1.0, kelly))
                        alloc_pct = min(kelly, 0.20) # Max 20%
                        
                        if alloc_pct > 0:
                            alloc_dollars = equity * alloc_pct
                            if alloc_dollars > cash: alloc_dollars = cash
                            
                            if alloc_dollars > 0:
                                try:
                                    if len(buy_tickers) > 1:
                                        entry_price = hist['Close'][t].iloc[0]
                                    else:
                                        entry_price = hist['Close'].iloc[0]
                                        
                                    holdings[t] = {'dollars': alloc_dollars, 'price': entry_price}
                                    cash -= alloc_dollars
                                    print(f"    Bought {t} | Alloc: ${alloc_dollars:.2f} (Kelly: {alloc_pct*100:.1f}%)")
                                except:
                                    pass
                except:
                    pass
                    
            os.remove(out_json)
        
        ledger.append({
            'Date': date_str,
            'Cash': round(cash, 2),
            'Equity': round(equity, 2),
            'Open_Positions': len(holdings)
        })
        
        print(f"  End of Day Equity: ${equity:.2f}")
        print("  => Commencing 60-second Thermal Cooldown before next day...")
        time.sleep(60)

    # Final settlement of last day's holdings
    equity = cash
    for t in holdings:
        equity += holdings[t]['dollars'] # Just value them at cost for final day
        
    print(f"\n>>> FINAL EQUITY FOR {test_name}: ${equity:.2f}")
    df_ledger = pd.DataFrame(ledger)
    df_ledger.to_csv(f"financial_data/Backtest_Ledger_{test_name}.csv", index=False)

# Load Champion
print("\n>>> Loading CHAMPION list from VIP_Tickers.json...")
with open("financial_data/VIP_Tickers.json", "r") as f:
    vip_data = json.load(f)['sectors_dict']
    
champ_tickers = []
for sec, ticks in vip_data.items():
    # Take top 15 to match the backtest size of the other two
    champ_tickers.extend(ticks[:15])

run_simulation("CHAMPION", list(set(champ_tickers)))
run_simulation("EL_CAP", el_cap_tickers)
run_simulation("EL_VOLTI", el_volti_tickers)

print("\n\n=== BACKTEST COMPLETELY FINISHED ===")
print(">>> Generating Final Olympic CSV Report...")

try:
    df_cap = pd.read_csv("financial_data/Backtest_Ledger_EL_CAP.csv")
    df_vol = pd.read_csv("financial_data/Backtest_Ledger_EL_VOLTI.csv")
    df_champ = pd.read_csv("financial_data/Backtest_Ledger_CHAMPION.csv")
    
    df_merged = df_cap[['Date', 'Equity']].rename(columns={'Equity': 'EL_CAP (70% Liquidity)'})
    df_merged = df_merged.merge(df_vol[['Date', 'Equity']].rename(columns={'Equity': 'EL_VOLTI (70% Stability)'}), on='Date', how='inner')
    df_merged = df_merged.merge(df_champ[['Date', 'Equity']].rename(columns={'Equity': 'CHAMPION (Live VIP)'}), on='Date', how='inner')
    
    current_month = pd.Timestamp.now().strftime('%Y_%m')
    out_file = f"financial_data/Olympic_Shootout_Results_{current_month}.csv"
    df_merged.to_csv(out_file, index=False)
    print(f">>> Saved: {out_file}")
except Exception as e:
    print(f"Failed to generate final CSV: {e}")
