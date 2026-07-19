import pandas as pd
import json
import os

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')

def get_blacklisted_tickers(persona="BallsForBrains", lookback_days=30, strike_threshold=3):
    """
    Scans the capital ledgers for a persona over the last `lookback_days` days.
    Returns a set of tickers that have `strike_threshold` or more negative PnL days.
    """
    ledger_path = os.path.join(BASE_DIR, f'Capital_Ledger_{persona}.csv')
    etf_ledger_path = os.path.join(BASE_DIR, f'ETF_Capital_Ledger_{persona}.csv')
    
    dfs = []
    if os.path.exists(ledger_path):
        dfs.append(pd.read_csv(ledger_path))
    if os.path.exists(etf_ledger_path):
        dfs.append(pd.read_csv(etf_ledger_path))
        
    if not dfs:
        return set()
        
    try:
        df = pd.concat(dfs, ignore_index=True)
        if 'Daily_PnL_JSON' not in df.columns or 'Date' not in df.columns:
            return set()
            
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date', ascending=False)
        
        # We only care about the last N unique dates
        recent_dates = df['Date'].drop_duplicates().head(lookback_days)
        df_recent = df[df['Date'].isin(recent_dates)]
        
        strikes = {}
        for idx, row in df_recent.iterrows():
            try:
                pnl = json.loads(row['Daily_PnL_JSON'])
                for ticker, profit in pnl.items():
                    if float(profit) < 0:
                        strikes[ticker] = strikes.get(ticker, 0) + 1
            except:
                pass
                
        blacklisted = {ticker: f"Blacklisted: {count} Strikes in {lookback_days}d" for ticker, count in strikes.items() if count >= strike_threshold}
        return blacklisted
    except Exception as e:
        print(f"Error reading ledgers for blacklist: {e}")
        return {}
