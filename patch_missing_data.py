import pandas as pd
import yfinance as yf

csv_path = 'C:/Users/AviShemla/AntiGravity/financial_data/SP500_Clean_Advanced_Analysis.csv'
print("Loading CSV...")
df = pd.read_csv(csv_path, parse_dates=['Date'])

max_dates = df.groupby('Ticker')['Date'].max()
missing_tickers = max_dates[max_dates < '2026-07-30'].index.tolist()
print(f"Found {len(missing_tickers)} missing tickers for 2026-07-30.")

if len(missing_tickers) > 0:
    print("Downloading 2026-07-30 data from Yahoo Finance...")
    data = yf.download(missing_tickers, start='2026-07-30', end='2026-07-31', progress=False)
    
    new_rows = []
    if isinstance(data.columns, pd.MultiIndex):
        for ticker in missing_tickers:
            if ticker in data['Close']:
                close = data['Close'][ticker].dropna()
                vol = data['Volume'][ticker].dropna()
                if not close.empty and not vol.empty:
                    new_rows.append({
                        'Date': close.index[0],
                        'Ticker': ticker,
                        'Close': close.iloc[0],
                        'Volume': vol.iloc[0]
                    })
    else:
        # Single ticker case if only 1 missing
        ticker = missing_tickers[0]
        if 'Close' in data.columns:
            close = data['Close'].dropna()
            vol = data['Volume'].dropna()
            if not close.empty and not vol.empty:
                new_rows.append({
                    'Date': close.index[0],
                    'Ticker': ticker,
                    'Close': close.iloc[0],
                    'Volume': vol.iloc[0]
                })
                
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        # We need to fill in other columns like RSI, MACD, SEC_REG. 
        # But for the bayesian scorecard, it mostly relies on 'Close' to calculate returns.
        # Actually, if we just append this, other columns will be NaN.
        # Wait, the scorecard uses returns_df generated from 'Close' using load_predictors.
        # load_predictors forward-fills NaN values, but we need the 'Close' to be accurate for today.
        
        # Let's append to the main df
        print(f"Appending {len(new_rows)} rows to CSV...")
        combined = pd.concat([df, new_df], ignore_index=True)
        combined.sort_values(by=['Ticker', 'Date'], inplace=True)
        combined.to_csv(csv_path, index=False)
        print("CSV Patched successfully!")
    else:
        print("Failed to download data.")
else:
    print("No tickers are missing data for 2026-07-30.")
