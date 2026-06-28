import pandas as pd
import json
import subprocess
import numpy as np
import os
import psutil
import atexit
import sys
import time

LOCK_FILE = r"C:\Users\AviShemla\AntiGravity\run_backtests.lock"
try:
    lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    def remove_lock():
        try:
            os.close(lock_fd)
        except:
            pass
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    atexit.register(remove_lock)
except FileExistsError:
    print("FATAL: Marathon Shootout is already running. OS Lockfile prevents duplicate execution.")
    sys.exit(1)

try:
    psutil.Process(os.getpid()).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
except:
    pass
import yfinance as yf

# Removed wait_for_pipeline() to prevent infinite deadlock when called by master_pipeline.py

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
        # For the daily run, we can take the full top 10 from each sector since it's only computing the 1-day delta.
        top_cap = group.sort_values('EL_CAP_Score', ascending=False).head(5)['Ticker'].tolist()
        top_vol = group.sort_values('EL_VOLTI_Score', ascending=False).head(5)['Ticker'].tolist()
        el_cap.extend(top_cap)
        el_volti.extend(top_vol)
    return list(set(el_cap)), list(set(el_volti))

el_cap_tickers, el_volti_tickers = generate_lists()
print(f"Loaded {len(el_cap_tickers)} tickers for EL_CAP, {len(el_volti_tickers)} for EL_VOLTI")

import os, sys
import pandas_market_calendars as mcal

olympic_csv_path = "financial_data/Olympic_Shootout_Results_MASTER.csv"

today = pd.to_datetime('today').normalize()
start_cash_dict = {"EL_CAP": 10000.0, "EL_VOLTI": 10000.0, "CHAMPION": 10000.0}

if os.path.exists(olympic_csv_path):
    print(f"\n>>> Loading marathon state from {olympic_csv_path}")
    try:
        df_marathon = pd.read_csv(olympic_csv_path)
        last_date_str = df_marathon['Date'].iloc[-1]
        last_date = pd.to_datetime(last_date_str).normalize()
        
        nyse = mcal.get_calendar('NYSE')
        trading_days = nyse.valid_days(start_date=last_date, end_date=today).tz_localize(None)
        
        if len(trading_days) > 1:
            trading_days = trading_days[1:] # Exclude the already simulated last_date
            # Only exclude the last day if it equals today (since today is incomplete)
            if trading_days[-1].date() == today.date():
                sim_dates = trading_days[:-1]
            else:
                sim_dates = trading_days
        else:
            sim_dates = []
            
        start_cash_dict["EL_CAP"] = float(df_marathon['EL_CAP (70% Liquidity)'].iloc[-1])
        start_cash_dict["EL_VOLTI"] = float(df_marathon['EL_VOLTI (70% Stability)'].iloc[-1])
        start_cash_dict["CHAMPION"] = float(df_marathon['CHAMPION (Live VIP)'].iloc[-1])
        print(f"    Resuming from: {last_date_str}")
        print(f"    Marathon Delta: {len(sim_dates)} new days to simulate.")
        
    except Exception as e:
        print(f"Error loading marathon state: {e}. Falling back to default 5 days.")
        nyse = mcal.get_calendar('NYSE')
        past_days = nyse.valid_days(start_date=today - pd.Timedelta(days=30), end_date=today).tz_localize(None)
        trading_days = past_days[-6:]
        sim_dates = trading_days[:-1] if trading_days[-1].date() == today.date() else trading_days
else:
    print(f"\n>>> No state found. Resuming manual override for June 25 and June 26.")
    nyse = mcal.get_calendar('NYSE')
    sim_dates = [pd.to_datetime('2026-06-25'), pd.to_datetime('2026-06-26')]
    
if len(sim_dates) == 0:
    print("\n>>> Marathon is already completely up to date! Nothing to simulate today.")
    sys.exit(0)

print(f"\n>>> Simulated Dates: {[d.strftime('%Y-%m-%d') for d in sim_dates]}")

# --- GLOBAL VIX FETCH FOR DYNAMIC STOP LOSSES ---
global_vix_hist_bt = pd.DataFrame()
try:
    import yfinance as yf
    global_vix_hist_bt = yf.Ticker('^VIX').history(period='100d')
except:
    pass

def run_simulation(test_name, tickers_list, start_cash=10000.0):
    print(f"\n=======================================================")
    print(f"STARTING SIMULATION: {test_name}")
    print(f"=======================================================\n")
    
    cash = start_cash
    holdings = {} # ticker -> {'dollars': X, 'price': Y}
    state_file = f"financial_data/marathon_state_{test_name}.json"
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state_data = json.load(f)
                if isinstance(state_data, dict) and "holdings" in state_data:
                    holdings = state_data["holdings"]
                    cash = state_data.get("cash", start_cash)
                else:
                    holdings = state_data
            print(f"    Loaded {len(holdings)} open positions from previous run.")
        except: pass
    ledger = []
    
    for i, date in enumerate(sim_dates):
        date_str = date.strftime('%Y-%m-%d')
        date_obj = date
        print(f"\n[{i+1}/{len(sim_dates)}] Simulating {date_str}...")
        
        # 1. Settle yesterday's holdings using current day's open/close prices
        if holdings:
            print(f"  Settling {len(holdings)} open positions on {date_str}...")
            # We fetch price data for the CURRENT day to prevent lookahead bias
            held_tickers = list(holdings.keys())
            try:
                # download data for the settlement day
                hist = yf.download(held_tickers, start=date_str, end=date_obj + pd.Timedelta(days=1), progress=False)
                for t in held_tickers:
                    alloc = holdings[t]['dollars']
                    entry_price = holdings[t]['price']
                    
                    try:
                        if len(held_tickers) > 1:
                            closes = hist['Close'][t]
                            lows = hist['Low'][t]
                        else:
                            closes = hist['Close']
                            lows = hist['Low']
                        
                        settle_price = closes.loc[date_str] if date_str in closes.index else closes.iloc[-1]
                        low_price = lows.loc[date_str] if date_str in lows.index else lows.iloc[-1]
                        
                        ret = (settle_price - entry_price) / entry_price
                        
                        # --- DYNAMIC VIX STOP-LOSS LOGIC (Championship Standard) ---
                        dynamic_stop_loss = -0.060 # Default BallsForBrains
                        vix_high = 0.0
                        if not global_vix_hist_bt.empty:
                            try:
                                if next_bday_str in global_vix_hist_bt.index.strftime('%Y-%m-%d'):
                                    vix_high = global_vix_hist_bt[global_vix_hist_bt.index.strftime('%Y-%m-%d') == next_bday_str]['High'].iloc[0]
                                else:
                                    vix_high = global_vix_hist_bt['High'].iloc[-1]
                                    
                                dynamic_stop_loss = -0.030 if vix_high > 35.0 else (-0.045 if vix_high > 25.0 else -0.060)
                            except: pass
                            
                        intraday_drop = (low_price - entry_price) / entry_price
                        if intraday_drop <= dynamic_stop_loss:
                            panic_str = f"(VIX {vix_high:.1f})" if vix_high > 0 else ""
                            print(f"    [STOP-LOSS] {t} dropped {intraday_drop*100:.1f}% intraday! Intercepting loss at {dynamic_stop_loss*100:.1f}% {panic_str}")
                            ret = dynamic_stop_loss
                            
                        pnl = alloc * ret
                        cash += (alloc + pnl)
                        print(f"    {t} Return: {ret*100:.2f}% -> PnL: ${pnl:.2f}")
                    except Exception as e:
                        print(f"    {t} failed to settle ({e}). Assuming 0% return.")
                        cash += alloc
            except Exception as e:
                print(f"  Warning: Failed to fetch settlement prices: {e}")
                for t in held_tickers: cash += holdings[t]['dollars']
        
        holdings.clear()
        
        # Now that all positions are settled, total equity is perfectly represented by our liquid cash
        equity = cash
        
        # 2. Spawn PyMC Worker to get predictions for `date_str`
        out_json = f"tmp_pred_{test_name}.json"
        tickers_csv = ",".join(tickers_list)
        
        cmd = ["py", "backtest_worker.py", "--date", date_str, "--tickers", tickers_csv, "--out", out_json]
        if os.path.exists(out_json):
            print(f"  [RECOVERY] Found existing predictions for {date_str}. Skipping Bayesian Subprocess to save 2 hours of compute!")
        else:
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
                    hist = yf.download(buy_tickers, start=date_str, end=date_obj + pd.Timedelta(days=1), progress=False)
                    for t in buy_tickers:
                        prob = buys[t]['prob']
                        ret = buys[t]['exp_ret']
                        vol = buys[t]['exp_vol'] if buys[t]['exp_vol'] > 0 else 0.01
                        
                        # Kelly
                        if ret <= 0.0001:
                            kelly = 0.0
                        else:
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

    try:
        with open(state_file, 'w') as f:
            json.dump({"cash": cash, "holdings": holdings}, f)
    except: pass

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
    # Take top 10 to match the backtest size of the other two
    champ_tickers.extend(ticks[:10])

# run_simulation("CHAMPION", list(set(champ_tickers)), start_cash_dict["CHAMPION"]) # Finished previously
run_simulation("EL_CAP", el_cap_tickers, start_cash_dict["EL_CAP"])
run_simulation("EL_VOLTI", el_volti_tickers, start_cash_dict["EL_VOLTI"])

print("\n\n=== BACKTEST COMPLETELY FINISHED ===")
print(">>> Generating Final Olympic CSV Report...")

try:
    df_cap = pd.read_csv("financial_data/Backtest_Ledger_EL_CAP.csv")
    df_vol = pd.read_csv("financial_data/Backtest_Ledger_EL_VOLTI.csv")
    df_champ = pd.read_csv("financial_data/Backtest_Ledger_CHAMPION.csv")
    
    df_merged = df_cap[['Date', 'Equity']].rename(columns={'Equity': 'EL_CAP (70% Liquidity)'})
    df_merged = df_merged.merge(df_vol[['Date', 'Equity']].rename(columns={'Equity': 'EL_VOLTI (70% Stability)'}), on='Date', how='inner')
    df_merged = df_merged.merge(df_champ[['Date', 'Equity']].rename(columns={'Equity': 'CHAMPION (Live VIP)'}), on='Date', how='inner')
    # Merge the individual tracking ledgers into the MASTER file
    out_file = "financial_data/Olympic_Shootout_Results_MASTER.csv"
    
    if os.path.exists(out_file):
        df_history = pd.read_csv(out_file)
        df_merged = pd.concat([df_history, df_merged], ignore_index=True)
        df_merged = df_merged.drop_duplicates(subset=['Date'], keep='last').sort_values('Date').reset_index(drop=True)
        
    df_merged.to_csv(out_file, index=False)
    print(f">>> Saved Marathon Update: {out_file}")
except Exception as e:
    print(f"Failed to generate final CSV: {e}")
