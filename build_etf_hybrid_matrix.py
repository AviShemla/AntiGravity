import pandas as pd
import numpy as np
import yfinance as yf
import os
from sklearn.linear_model import LogisticRegression
from etf_whale_extractor import get_60_percent_whales
import os
from etf_whale_extractor import get_60_percent_whales

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
os.makedirs(BASE_DIR, exist_ok=True)

# Standard Macro-Economic tracking ETFs
MACRO_ETFS = ['SPY', 'TLT', 'GLD', 'UUP']

def build_hybrid_matrix(target_etf, period='5y'):
    print(f"--- Building Hybrid Matrix for {target_etf} ---")
    
    # 1. Get the Micro Whales
    print("1. Extracting 60% Whales...")
    whales = get_60_percent_whales(target_etf)
    if not whales:
        print(f"[WARNING] No whales found for {target_etf}. Building matrix using only the ETF and Macro indicators.")
        whales = []
        
    print(f"   Identified {len(whales)} whales: {whales}")
    
    # 2. Define the full universe to download including VIX
    universe = [target_etf, '^VIX'] + MACRO_ETFS + whales
    
    # 3. Download Data
    print(f"2. Downloading historical data for {len(universe)} symbols...")
    from failover_downloader import download_ticker_with_failover
    dfs = {}
    for ticker in universe:
        df = download_ticker_with_failover(ticker, period=period)
        if not df.empty:
            dfs[ticker] = df
        else:
            print(f"[WARNING] Failed to retrieve data for {ticker} during ETF Hybrid build.")
            
    # Combine into multi-index columns:
    reformatted_dfs = {}
    for ticker, df in dfs.items():
        # Ensure standard columns are present
        for col in ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']:
            if col not in df.columns:
                df[col] = np.nan
        df.columns = pd.MultiIndex.from_product([[ticker], df.columns])
        reformatted_dfs[ticker] = df
        
    if reformatted_dfs:
        data = pd.concat(reformatted_dfs.values(), axis=1)
    else:
        data = pd.DataFrame()
    
    # 4. Process Features
    print("3. Calculating causal lag features...")
    feature_dfs = []
    
    for ticker in universe:
        try:
            if ticker not in dfs:
                if ticker == target_etf:
                    raise ValueError(f"Target ETF {target_etf} failed to download. Cannot build matrix.")
                continue
                
            df = data[ticker].copy()
                
            df = df[['Close']].dropna()
            
            # Calculate Daily Return %
            ret = df['Close'].pct_change() * 100
            
            # Create a temporary dataframe for this ticker's features
            ticker_df = pd.DataFrame(index=df.index)
            
            if ticker == target_etf:
                # For the target ETF, we need the actual Target values (Today's Return and Direction)
                ticker_df[f'{ticker}_Return_%'] = ret
                ticker_df[f'{ticker}_Direction'] = (ret > 0).astype(int)
            
            # For ALL tickers (including Target), calculate causal Lags (Yesterday, 2 days ago, 3 days ago, etc)
            ticker_df[f'{ticker}_Lag1'] = ret.shift(1)
            ticker_df[f'{ticker}_Lag2'] = ret.shift(2)
            ticker_df[f'{ticker}_Lag3'] = ret.shift(3)
            ticker_df[f'{ticker}_Lag4'] = ret.shift(4)
            ticker_df[f'{ticker}_Lag5'] = ret.shift(5)
            
            # FAST NESTED PREDICTION FOR WHALES
            if ticker in whales:
                # We use a fast Logistic Regression to generate historical nested probabilities
                lag_data = ticker_df.copy().dropna()
                if not lag_data.empty and len(lag_data) > 100:
                    X = lag_data[[f'{ticker}_Lag1', f'{ticker}_Lag2', f'{ticker}_Lag3', f'{ticker}_Lag4', f'{ticker}_Lag5']]
                    y = (lag_data[f'{ticker}_Lag1'].shift(-1) > 0).astype(int) # Predict next day (shift -1 of lag1 is today's return)
                    y = y.fillna(0)
                    
                    lr = LogisticRegression(solver='liblinear')
                    lr.fit(X, y)
                    probs = lr.predict_proba(X)[:, 1]
                    
                    # Map back to full ticker_df
                    nested_probs = pd.Series(index=lag_data.index, data=probs)
                    ticker_df[f'{ticker}_Nested_P_UP'] = nested_probs
            
            # MARKET FEAR & VOLATILITY FEATURES FOR TARGET
            if ticker == target_etf:
                ticker_df[f'{ticker}_Daily_STDEV'] = ret.rolling(20).std()
                
            if ticker == '^VIX':
                ticker_df['VIX_Close'] = df['Close']
            else:
                feature_dfs.append(ticker_df)
                
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            
    # 5. Merge everything
    print("4. Merging Matrix...")
    hybrid_matrix = pd.concat(feature_dfs, axis=1)
    
    # Drop rows with NaN
    hybrid_matrix = hybrid_matrix.dropna()
    
    # Calculate Market Fear Level
    if 'VIX_Close' in hybrid_matrix.columns and f'{target_etf}_Daily_STDEV' in hybrid_matrix.columns:
        hybrid_matrix['Market_Fear_Level'] = hybrid_matrix['VIX_Close'] / hybrid_matrix[f'{target_etf}_Daily_STDEV']
    
    # 6. Save to CSV
    output_path = os.path.join(BASE_DIR, f'{target_etf}_Hybrid_Matrix.csv')
    hybrid_matrix.to_csv(output_path)
    
    print(f"SUCCESS: Hybrid Matrix built with shape {hybrid_matrix.shape}")
    print(f"Saved to: {output_path}\n")
    return hybrid_matrix

if __name__ == '__main__':
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else 'XLK'
    build_hybrid_matrix(target)
