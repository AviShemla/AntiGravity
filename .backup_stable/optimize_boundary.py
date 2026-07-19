import os
import pandas as pd
import numpy as np

excel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Top5_Bayesian_Scorecard.xlsx')
print(f"Reading probabilities from {excel_path}...\n")

tickers = ['MU', 'CRL', 'NCLH', 'ROKU', 'TSLA']
thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]

results = []

for thresh in thresholds:
    total_trades = 0
    total_hits = 0
    total_return_pct = 0.0
    
    for ticker in tickers:
        df = pd.read_excel(excel_path, sheet_name=ticker)
        
        p_up = df['Bayesian_Prob_UP']
        actual_ret = df['Raw_Return_%']
        actual_dir = df['Actual_Direction']
        
        # Determine trades
        buys = p_up >= thresh
        sells = p_up <= (1 - thresh)
        
        # Calculate returns (Long on Buy, Short on Sell)
        # Assuming we capture the raw return when buying, and the negative raw return when shorting
        buy_returns = actual_ret[buys]
        sell_returns = -actual_ret[sells]
        
        # Calculate Hits
        buy_hits = actual_dir[buys] == 'UP'
        sell_hits = actual_dir[sells] == 'DOWN'
        
        total_trades += (buys.sum() + sells.sum())
        total_hits += (buy_hits.sum() + sell_hits.sum())
        # Raw_Return_% is already in percent (e.g. 1.5 for 1.5%)
        total_return_pct += (buy_returns.sum() + sell_returns.sum())
        
    hit_rate = (total_hits / total_trades) if total_trades > 0 else 0.0
    
    results.append({
        'Threshold': f">{thresh*100:.0f}%",
        'Total Trades (Top 5)': total_trades,
        'Hit Rate': hit_rate,
        'Total Return (Long/Short)': total_return_pct
    })

res_df = pd.DataFrame(results)
res_df['Hit Rate'] = (res_df['Hit Rate'] * 100).round(1).astype(str) + '%'
res_df['Total Return (Long/Short)'] = res_df['Total Return (Long/Short)'].round(2).astype(str) + '%'

print("=== OPTIMAL BOUNDARY ANALYSIS (Over 30 Days across Top 5 Tickers) ===")
print(res_df.to_string(index=False))
