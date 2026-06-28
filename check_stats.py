import sqlite3
import pandas as pd
import yfinance as yf

# Fetch BallsForBrains latest trades
conn = sqlite3.connect('C:/Users/AviShemla/AntiGravity/antigravity.db')
df = pd.read_sql("SELECT date, holdings_json, daily_pnl_json FROM capital_ledgers WHERE persona='BallsForBrains' ORDER BY date DESC LIMIT 2", conn)
print('--- BallsForBrains Ledger ---')
for i, row in df.iterrows():
    print(f"Date: {row['date']}, Holdings: {row['holdings_json']}, PnL: {row['daily_pnl_json']}")
conn.close()

# Fetch Actual Returns for top tickers
tickers = ['NDAQ', 'NEE', 'MCD', 'ADM', 'BLK']
print('\n=== ACTUAL RETURNS (Last Trade Day) ===')
for t in tickers:
    try:
        hist = yf.download(t, period='5d', progress=False)
        closes = hist['Close'].iloc[-3:]
        pct_change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100
        print(f'{t}: {pct_change.item():.2f}%')
    except Exception as e:
        print(f'{t}: Error fetching data')
