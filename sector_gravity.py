import yfinance as yf
import pandas as pd
import json
import os
import datetime

# Map VIP_Tickers.json sector keys to standard SPDR Sector ETFs
SECTOR_TO_ETF = {
    "Communication_Services": "XLC",
    "Consumer_Discretionary": "XLY",
    "Consumer_Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health_Care": "XLV",
    "Industrials": "XLI",
    "Information_Technology": "XLK",
    "Materials": "XLB",
    "Real_Estate": "XLRE",
    "Utilities": "XLU"
}

def load_stock_to_etf_map():
    vip_path = os.path.join(os.path.dirname(__file__), 'financial_data', 'VIP_Tickers.json')
    if not os.path.exists(vip_path):
        return {}
    with open(vip_path, 'r') as f:
        data = json.load(f)
    
    stock_to_etf = {}
    for sector_name, tickers in data.get('sectors_dict', {}).items():
        etf_ticker = SECTOR_TO_ETF.get(sector_name)
        if etf_ticker:
            for t in tickers:
                stock_to_etf[t] = etf_ticker
    return stock_to_etf

def build_gravity_map(date_str=None, momentum_days=5):
    """
    Downloads Sector ETFs and SPY, calculates momentum.
    Returns a dict mapping ETF ticker to a boolean (True=Green, False=Red).
    A sector is RED if its momentum is negative AND worse than SPY.
    """
    end_date = pd.to_datetime(date_str) if date_str else pd.to_datetime('today')
    start_date = end_date - pd.Timedelta(days=momentum_days + 15)
    
    tickers = list(SECTOR_TO_ETF.values()) + ['SPY']
    print(f"    [Sector Gravity] Fetching ETF Momentum Data up to {end_date.strftime('%Y-%m-%d')}...")
    
    try:
        # yfinance download returns a MultiIndex column DataFrame if multiple tickers are given
        df = yf.download(tickers, start=start_date.strftime('%Y-%m-%d'), end=(end_date + pd.Timedelta(days=1)).strftime('%Y-%m-%d'), progress=False)
        if 'Close' in df.columns.levels[0]:
            df = df['Close']
        else:
            df = df.xs('Close', level=0, axis=1, drop_level=True)
            
        df = df.ffill().dropna()
        
        # Make sure we have enough data
        if len(df) < momentum_days:
            print("    [Sector Gravity] Not enough historical data. Defaulting all to GREEN.")
            return {etf: True for etf in SECTOR_TO_ETF.values()}
            
        # Calculate N-day momentum
        momentum = (df.iloc[-1] - df.iloc[-momentum_days]) / df.iloc[-momentum_days]
        spy_mom = momentum['SPY']
        
        gravity_map = {}
        red_count = 0
        for etf in SECTOR_TO_ETF.values():
            if etf not in momentum:
                gravity_map[etf] = True
                continue
                
            etf_mom = momentum[etf]
            # Rule: If ETF is negative AND worse than SPY, it's a bleeding sector
            if etf_mom < 0 and etf_mom < spy_mom:
                gravity_map[etf] = False
                red_count += 1
            else:
                gravity_map[etf] = True
                
        print(f"    [Sector Gravity] Complete! SPY Momentum: {spy_mom*100:.2f}%. Detected {red_count} RED sectors.")
        return gravity_map
        
    except Exception as e:
        print(f"    [Sector Gravity] Failed to fetch data: {e}. Defaulting to GREEN.")
        return {etf: True for etf in SECTOR_TO_ETF.values()}

if __name__ == "__main__":
    gmap = build_gravity_map()
    print("Gravity Map:", gmap)
