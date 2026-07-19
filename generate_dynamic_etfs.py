import pandas as pd
import numpy as np
import yfinance as yf
import os
import json

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
os.makedirs(BASE_DIR, exist_ok=True)

# Load the dynamically generated Master Universe from the Sunday Screener
MASTER_UNIVERSE_PATH = os.path.join(BASE_DIR, 'Master_ETF_Universe.json')

if os.path.exists(MASTER_UNIVERSE_PATH):
    with open(MASTER_UNIVERSE_PATH, 'r') as f:
        ETF_UNIVERSE = json.load(f)
else:
    print(f"CRITICAL WARNING: {MASTER_UNIVERSE_PATH} not found!")
    print("Falling back to absolute baseline 11 GICS sectors.")
    ETF_UNIVERSE = ["XLK", "XLV", "XLY", "XLF", "XLC", "XLI", "XLE", "XLP", "XLU", "XLRE", "XLB"]

TOP_N = 10

def generate_dynamic_target_list():
    print("=== DYNAMIC ETF SCREENER: SCANNING MARKET OPPORTUNITIES ===")
    print(f"Scanning Universe of {len(ETF_UNIVERSE)} ETFs for extreme momentum and volatility...")
    
    results = []
    
    # Download last 3 months of data to get 30 trading days
    data = yf.download(ETF_UNIVERSE, period="3mo", progress=False)['Close']
    
    # If the user is missing yfinance multi-download, fallback to single downloads
    if data.empty or not isinstance(data.columns, pd.Index):
        print("Fallback: Single sequential downloads...")
        dfs = []
        for ticker in ETF_UNIVERSE:
            try:
                hist = yf.Ticker(ticker).history(period="3mo")
                if not hist.empty:
                    close = hist['Close']
                    close.name = ticker
                    dfs.append(close)
            except:
                pass
        if dfs:
            data = pd.concat(dfs, axis=1)
            
    if data.empty:
        print("CRITICAL ERROR: Failed to download market data. Falling back to Core 11 Sectors.")
        fallback = ["XLK", "XLV", "XLY", "XLF", "XLC", "XLI", "XLE", "XLP", "XLU", "XLRE", "XLB"]
        with open(os.path.join(BASE_DIR, 'Dynamic_Target_ETFs.json'), 'w') as f:
            json.dump(fallback, f)
        return

    # Calculate 30-Day Trading Momentum and Volatility
    for ticker in data.columns:
        series = data[ticker].dropna()
        if len(series) < 30:
            continue
            
        recent_30 = series.tail(30)
        
        # 30-Day Total Return (Momentum)
        momentum_return = (recent_30.iloc[-1] - recent_30.iloc[0]) / recent_30.iloc[0]
        
        # 30-Day Annualized Volatility
        daily_returns = recent_30.pct_change().dropna()
        annualized_vol = daily_returns.std() * np.sqrt(252)
        
        # Advanced Ranking Metric: Momentum * Volatility 
        # (We want explosive upside. High return + High volatility = massive opportunity)
        # If momentum is negative, this metric pushes it aggressively down the list.
        opportunity_score = momentum_return * annualized_vol
        
        results.append({
            "ETF": ticker,
            "Momentum_30d": momentum_return,
            "Volatility_Ann": annualized_vol,
            "Opportunity_Score": opportunity_score
        })
        
    df_results = pd.DataFrame(results)
    
    # Sort by Opportunity Score Descending
    df_results = df_results.sort_values(by="Opportunity_Score", ascending=False).reset_index(drop=True)
    
    print("\n--- TOP 10 DYNAMIC ETF TARGETS FOR THIS WEEK ---")
    top_10 = df_results.head(TOP_N)
    for i, row in top_10.iterrows():
        print(f"#{i+1} {row['ETF'].ljust(5)} | Score: {row['Opportunity_Score']:.4f} | 30d Return: {row['Momentum_30d']*100:+.1f}% | Vol: {row['Volatility_Ann']*100:.1f}%")
        
    # Extract just the ticker strings
    final_targets = top_10['ETF'].tolist()
    
    # Save to JSON for the Daily Pipeline to read
    out_path = os.path.join(BASE_DIR, 'Dynamic_Target_ETFs.json')
    
    # Compare with old targets
    if os.path.exists(out_path):
        try:
            with open(out_path, 'r') as f:
                old_targets = json.load(f)
        except:
            old_targets = []
    else:
        old_targets = []
        
    kept = sorted(list(set(final_targets) & set(old_targets)))
    added = sorted(list(set(final_targets) - set(old_targets)))
    dropped = sorted(list(set(old_targets) - set(final_targets)))
    
    changes_path = os.path.join(BASE_DIR, 'Dynamic_ETF_Changes.json')
    with open(changes_path, 'w') as f:
        json.dump({"Kept": kept, "Added": added, "Dropped": dropped}, f, indent=4)

    with open(out_path, 'w') as f:
        json.dump(final_targets, f, indent=4)
        
    print(f"\nSUCCESS: Dynamically injected {TOP_N} high-octane ETFs into the pipeline engine!")
    print(f"Saved to: {out_path}\n")

if __name__ == "__main__":
    generate_dynamic_target_list()
