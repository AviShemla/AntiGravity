import pandas as pd
import yfinance as yf
import requests
import io

print(">>> Scraping S&P 500...")
headers = {'User-Agent': 'Mozilla/5.0'}
html = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers).text
sp500_df = pd.read_html(io.StringIO(html))[0]

tickers = sp500_df['Symbol'].tolist()
tickers = [t.replace('.', '-') for t in tickers]
sectors = sp500_df['GICS Sector'].tolist()
ticker_sector_map = dict(zip(tickers, sectors))

print(f">>> Downloading 1y data for {len(tickers)} tickers...")
data = yf.download(tickers, period="1y", group_by="ticker", auto_adjust=False, progress=False)

results = []
for t in tickers:
    try:
        if len(tickers) == 1:
            df = data
        else:
            df = data[t]
        
        if df.empty or 'Close' not in df.columns or 'Volume' not in df.columns:
            continue
            
        df = df.dropna(subset=['Close', 'Volume'])
        if len(df) < 50:
            continue
            
        recent_df = df.tail(30)
        avg_liquidity = (recent_df['Close'] * recent_df['Volume']).mean()
        
        returns = df['Close'].pct_change().dropna()
        volatility = returns.std()
        
        if volatility > 0:
            results.append({
                'Ticker': t.replace('-', '.'), 
                'Sector': ticker_sector_map.get(t, "Unknown").replace(' ', '_'),
                'Liquidity': avg_liquidity,
                'Volatility': volatility
            })
    except:
        pass

df = pd.DataFrame(results)

# Normalize metrics between 0 and 1 so we can weight them properly
for sec in df['Sector'].unique():
    sec_mask = df['Sector'] == sec
    
    # Cap (Higher is better) -> min/max scaling
    min_l = df.loc[sec_mask, 'Liquidity'].min()
    max_l = df.loc[sec_mask, 'Liquidity'].max()
    df.loc[sec_mask, 'Norm_Cap'] = (df.loc[sec_mask, 'Liquidity'] - min_l) / (max_l - min_l) if max_l > min_l else 0
    
    # Volatility (Lower is better) -> inverse min/max scaling
    min_v = df.loc[sec_mask, 'Volatility'].min()
    max_v = df.loc[sec_mask, 'Volatility'].max()
    df.loc[sec_mask, 'Norm_Vol'] = 1 - ((df.loc[sec_mask, 'Volatility'] - min_v) / (max_v - min_v)) if max_v > min_v else 0

# Calculate specific scores
df['EL_CAP_Score'] = (df['Norm_Cap'] * 0.70) + (df['Norm_Vol'] * 0.30)
df['EL_VOLTI_Score'] = (df['Norm_Cap'] * 0.30) + (df['Norm_Vol'] * 0.70)

# Build EL_CAP_SPY List
el_cap_list = {}
for sector, group in df.groupby('Sector'):
    top_50 = group.sort_values('EL_CAP_Score', ascending=False).head(50)
    el_cap_list[sector] = top_50['Ticker'].tolist()

# Build EL_VOLTI_SPY List
el_volti_list = {}
for sector, group in df.groupby('Sector'):
    top_50 = group.sort_values('EL_VOLTI_Score', ascending=False).head(50)
    el_volti_list[sector] = top_50['Ticker'].tolist()

print("\n=== TOP 5 INFO TECH TICKERS (CAP 70% | VOL 30%) ===")
print(el_cap_list.get('Information_Technology', [])[:5])

print("\n=== TOP 5 INFO TECH TICKERS (CAP 30% | VOL 70%) ===")
print(el_volti_list.get('Information_Technology', [])[:5])

# Calculate total diffs
total_diffs = 0
for sec in el_cap_list.keys():
    cap_set = set(el_cap_list[sec])
    vol_set = set(el_volti_list[sec])
    diff = len(cap_set ^ vol_set) / 2 # number of swaps
    total_diffs += diff

print(f"\nTotal Ticker Swaps between the two lists: {int(total_diffs)}")
