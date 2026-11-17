import pandas as pd
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database_manager

def get_blacklisted_tickers(persona="BallsForBrains", lookback_days=15, strike_threshold=3):
    """
    Scans the Turso capital_ledgers for a persona over the last `lookback_days` days.
    Returns a dict of tickers that have `strike_threshold` or more negative PnL days.
    """
    dfs = []
    try:
        df_stock = database_manager.get_ledger(persona)
        if not df_stock.empty:
            dfs.append(df_stock)
    except Exception:
        pass
    try:
        etf_p = persona if str(persona).startswith("ETF_") else f"ETF_{persona}"
        df_etf = database_manager.get_ledger(etf_p)
        if not df_etf.empty:
            dfs.append(df_etf)
    except Exception:
        pass

    if not dfs:
        return {}

    try:
        df = pd.concat(dfs, ignore_index=True)
        if 'Daily_PnL_JSON' not in df.columns or 'Date' not in df.columns:
            return {}

        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values('Date', ascending=False)

        recent_dates = df['Date'].drop_duplicates().head(lookback_days)
        df_recent = df[df['Date'].isin(recent_dates)]

        strikes = {}
        for idx, row in df_recent.iterrows():
            try:
                pnl = json.loads(row['Daily_PnL_JSON'])
                for ticker, profit in pnl.items():
                    if float(profit) < 0:
                        strikes[ticker] = strikes.get(ticker, 0) + 1
            except Exception:
                pass

        blacklisted = {ticker: f"Blacklisted: {count} Strikes in {lookback_days}d" for ticker, count in strikes.items() if count >= strike_threshold}
        return blacklisted
    except Exception as e:
        print(f"Error reading Turso ledgers for blacklist: {e}")
        return {}

