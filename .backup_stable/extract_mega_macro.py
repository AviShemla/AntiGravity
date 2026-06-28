import yfinance as yf
import pandas as pd
import numpy as np
import os
import time

def extract_mega_macro():
    print("=== EXTRACTING MEGA-MACRO PHASE 1 PREDICTORS ===")
    
    BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
    DATA_DIR = os.path.join(BASE_DIR, "financial_data")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    tickers = {
        'TNX': '^TNX', # 10-Year Yield
        'IRX': '^IRX', # 13-Week Yield
        'HYG': 'HYG',  # High Yield Corporate
        'IEF': 'IEF',  # Safe Treasuries
        'SPHB': 'SPHB', # High Beta
        'SPLV': 'SPLV', # Low Volatility
        'OIL': 'CL=F',  # Crude Oil
        'COPPER': 'HG=F', # Copper
        'USD': 'UUP'    # US Dollar
    }
    
    # Download 5 years of data safely using the sequential loop trick to avoid Yahoo Finance rate limits
    print("Downloading massive historical datasets from Yahoo Finance with safe delays...")
    
    close_prices = pd.DataFrame()
    for name, symbol in tickers.items():
        try:
            print(f"  -> Extracting {symbol}...")
            ticker_obj = yf.Ticker(symbol)
            hist = ticker_obj.history(period="5y", interval="1d")
            if not hist.empty and 'Close' in hist.columns:
                hist.index = pd.to_datetime(hist.index).tz_localize(None).normalize()
                hist = hist[~hist.index.duplicated(keep='last')]
                close_prices[f'{name}_Close'] = hist['Close']
            time.sleep(2) # 2-second delay trick to avoid IP block
        except Exception as e:
            print(f"Warning: Failed to extract {symbol} -> {e}")
            
    # Forward fill missing days (e.g., if a commodity market was closed on a stock market day)
    close_prices = close_prices.ffill().dropna()
    
    print("Engineering Institutional Spread and Flow Tensors...")
    features = pd.DataFrame(index=close_prices.index)
    
    # 1. Yield Curve Spread (10Y minus 13W)
    if 'TNX_Close' in close_prices.columns and 'IRX_Close' in close_prices.columns:
        features['Yield_Curve_Spread'] = close_prices['TNX_Close'] - close_prices['IRX_Close']
        features['Yield_Curve_Trend_5d'] = features['Yield_Curve_Spread'].diff(5)
        
    # 2. Corporate Credit Spread Ratio (High Yield / Safe Treasuries)
    if 'HYG_Close' in close_prices.columns and 'IEF_Close' in close_prices.columns:
        features['Credit_Spread_Ratio'] = close_prices['HYG_Close'] / close_prices['IEF_Close']
        features['Credit_Spread_Trend_5d'] = features['Credit_Spread_Ratio'].pct_change(5)
        
    # 3. Risk-On Flow Spread (High Beta / Low Volatility)
    if 'SPHB_Close' in close_prices.columns and 'SPLV_Close' in close_prices.columns:
        features['Risk_On_Ratio'] = close_prices['SPHB_Close'] / close_prices['SPLV_Close']
        features['Risk_On_Trend_5d'] = features['Risk_On_Ratio'].pct_change(5)
        
    # 4. Commodity & Currency Flows (Raw Returns and Trends)
    for asset in ['OIL', 'COPPER', 'USD']:
        col = f'{asset}_Close'
        if col in close_prices.columns:
            features[f'{asset}_Return'] = close_prices[col].pct_change()
            features[f'{asset}_Trend_5d'] = close_prices[col].pct_change(5)
            
    # Also include the raw TNX returns as baseline
    if 'TNX_Close' in close_prices.columns:
        features['TNX_Return'] = close_prices['TNX_Close'].pct_change()
        features['TNX_Trend_5d'] = close_prices['TNX_Close'].pct_change(5)
        
    features = features.dropna()
    
    # Reset index to have 'Date' as a clean column
    features = features.reset_index()
    # Format date to match standard AntiGravity formats
    features['Date'] = pd.to_datetime(features['Date']).dt.tz_localize(None)
    
    output_path = os.path.join(DATA_DIR, "Mega_Macro_Features.csv")
    features.to_csv(output_path, index=False)
    
    print(f"SUCCESS: Engineered {len(features.columns)-1} Mega-Macro Tensors.")
    print(f"Saved {len(features)} historical trading days to {output_path}")

if __name__ == "__main__":
    # Add simple exponential backoff for rate limits
    for i in range(3):
        try:
            extract_mega_macro()
            break
        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                wait = (i + 1) * 10
                print(f"Rate limited by Yahoo Finance. Retrying in {wait} seconds...")
                time.sleep(wait)
            else:
                raise e
