import requests
import pandas as pd
import io

def get_60_percent_whales(ticker, target_weight=60.0):
    """
    Downloads the daily ETF constituents from State Street and returns the top stocks
    that collectively make up `target_weight`% of the ETF.
    """
    url = f"https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{ticker.lower()}.xlsx"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64 AppleWebKit/537.36)'}
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            print(f"Error fetching {ticker}: HTTP {res.status_code}")
            return []
            
        # Parse Excel, skipping header rows
        df = pd.read_excel(io.BytesIO(res.content), skiprows=4)
        
        # Clean up data
        df = df.dropna(subset=['Ticker', 'Weight'])
        
        # Ensure weight is a float
        df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce').fillna(0.0)
        
        # Sort by weight descending just to be safe
        df = df.sort_values(by='Weight', ascending=False).reset_index(drop=True)
        
        cumulative_weight = 0.0
        whales = []
        
        for index, row in df.iterrows():
            stock = str(row['Ticker']).strip()
            # Some tickers have asterisks or strange formats (e.g. BRK.B vs BRK-B)
            # SSGA usually uses BRK.B. We should clean it to yfinance standard if needed,
            # but for now we just take the literal ticker.
            stock = stock.replace('.', '-')
            
            w = row['Weight']
            
            whales.append(stock)
            cumulative_weight += w
            
            if cumulative_weight >= target_weight:
                break
                
        return whales
        
    except Exception as e:
        print(f"Error parsing ETF {ticker}: {e}")
        return []

def get_60_percent_whales_with_weights(ticker, target_weight=60.0):
    """
    Returns a dictionary of {ticker: weight} for the top whales that make up the target_weight.
    """
    url = f"https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{ticker.lower()}.xlsx"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64 AppleWebKit/537.36)'}
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            return {}
            
        df = pd.read_excel(io.BytesIO(res.content), skiprows=4)
        df = df.dropna(subset=['Ticker', 'Weight'])
        df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce').fillna(0.0)
        df = df.sort_values(by='Weight', ascending=False).reset_index(drop=True)
        
        cumulative_weight = 0.0
        whales = {}
        
        for index, row in df.iterrows():
            stock = str(row['Ticker']).strip().replace('.', '-')
            w = row['Weight']
            
            whales[stock] = w
            cumulative_weight += w
            
            if cumulative_weight >= target_weight:
                break
                
        return whales
        
    except Exception as e:
        print(f"Error parsing ETF {ticker}: {e}")
        return {}

if __name__ == '__main__':
    print("--- 60% WHALE EXTRACTION TEST ---")
    for t in ['XLK', 'XLF', 'XLY', 'XLV']:
        whales = get_60_percent_whales(t)
        print(f"\n{t} Whales (n={len(whales)}): {whales}")
