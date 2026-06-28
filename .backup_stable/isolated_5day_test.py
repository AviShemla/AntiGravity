import pandas as pd
import json
import subprocess
import os
import yfinance as yf

print("\n>>> Loading CHAMPION list from VIP_Tickers.json...")
with open("financial_data/VIP_Tickers.json", "r") as f:
    vip_data = json.load(f)['sectors_dict']

champ_tickers = []
for sec, ticks in vip_data.items():
    champ_tickers.extend(ticks[:15])

champ_tickers = list(set(champ_tickers))

today = pd.to_datetime('today').normalize()
trading_days = pd.bdate_range(end=today, periods=6)
sim_dates = trading_days[:-1]

test_name = "ISOLATED_TEST"
cash = 10000.0
holdings = {}

print(f"\n=======================================================")
print(f"STARTING 5-DAY ISOLATED SIMULATION: CHAMPION LIST")
print(f"=======================================================\n")

for i, date in enumerate(sim_dates):
    date_str = date.strftime('%Y-%m-%d')
    print(f"\n[{i+1}/{len(sim_dates)}] Simulating {date_str}...")
    
    next_bday = trading_days[i+1]
    next_bday_str = next_bday.strftime('%Y-%m-%d')
    
    equity = cash
    if holdings:
        held_tickers = list(holdings.keys())
        try:
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
                except:
                    cash += alloc
                    equity += alloc
        except:
            for t in held_tickers: cash += holdings[t]['dollars']; equity += holdings[t]['dollars']
    
    holdings.clear()
    
    out_json = f"tmp_pred_{test_name}.json"
    tickers_csv = ",".join(champ_tickers)
    
    python_exe = r"C:\Users\AviShemla\AppData\Local\Python\bin\python.exe"
    if not os.path.exists(python_exe):
        python_exe = "python"
        
    cmd = [python_exe, "backtest_worker.py", "--date", date_str, "--tickers", tickers_csv, "--out", out_json]
    subprocess.run(cmd, capture_output=True)
    
    if os.path.exists(out_json):
        with open(out_json, 'r') as f:
            preds = json.load(f)
            
        buys = {k: v for k, v in preds.items() if v['prob'] > 0.5 and v['exp_ret'] > 0}
        
        buy_tickers = list(buys.keys())
        if buy_tickers:
            try:
                hist = yf.download(buy_tickers, start=date_str, end=next_bday, progress=False)
                for t in buy_tickers:
                    prob = buys[t]['prob']
                    ret = buys[t]['exp_ret']
                    vol = buys[t]['exp_vol'] if buys[t]['exp_vol'] > 0 else 0.01
                    
                    kelly = prob - ((1 - prob) / (ret / vol))
                    kelly = max(0.0, min(1.0, kelly))
                    alloc_pct = min(kelly, 0.20)
                    
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
                                print(f"    Bought {t} | Alloc: ${alloc_dollars:.2f} (Kelly: {alloc_pct*100:.1f}%) | P(UP): {prob*100:.1f}%")
                            except: pass
            except: pass
        os.remove(out_json)
        
    print(f"  End of Day Equity: ${equity:.2f}")

print("\n=======================================================")
print(f">>> FINAL EQUITY AFTER 5 DAYS: ${equity:.2f}")
print("=======================================================\n")
