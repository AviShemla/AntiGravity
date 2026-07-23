import pandas as pd
import os
import yfinance as yf
from datetime import datetime

CSV_PATH = os.path.join("financial_data", "SP500_Clean_Advanced_Analysis.csv")
TARGET_DATE = "2026-07-22"

print(f"Heal SP500 starting for {TARGET_DATE}...")
df = pd.read_csv(CSV_PATH)
df['Date'] = pd.to_datetime(df['Date'])

for ticker in ['HUBB', 'SNPS']:
    ticker_df = df[df['Ticker'] == ticker].sort_values('Date')
    if ticker_df.empty:
        continue
    last_date = ticker_df['Date'].max()
    if last_date < pd.to_datetime(TARGET_DATE):
        print(f"Fetching {ticker} data to heal gap...")
        stock = yf.download(ticker, start=last_date.strftime('%Y-%m-%d'), end="2026-07-24", progress=False)
        if not stock.empty and TARGET_DATE in stock.index.strftime('%Y-%m-%d').values:
            target_idx = list(stock.index.strftime('%Y-%m-%d')).index(TARGET_DATE)
            close_val = stock['Close'].iloc[target_idx]
            close_price = float(close_val.iloc[0] if isinstance(close_val, pd.Series) else close_val)
            vol_val = stock['Volume'].iloc[target_idx]
            volume = int(vol_val.iloc[0] if isinstance(vol_val, pd.Series) else vol_val)
            
            # Duplicate the last row and update Date, Close, Volume
            new_row = ticker_df.iloc[-1].copy()
            new_row['Date'] = pd.to_datetime(TARGET_DATE)
            new_row['Close'] = close_price
            new_row['Volume'] = volume
            
            # We don't have perfect technicals calculated here, so we forward-fill the rest
            
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            print(f"Added {TARGET_DATE} row for {ticker}. Close: {close_price}")

df = df.sort_values(by=['Ticker', 'Date'])
df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
df.to_csv(CSV_PATH, index=False)
print("SP500 CSV successfully healed.")
os._exit(0)
