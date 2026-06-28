import pandas as pd
import numpy as np
import os

input_file = r'C:\Users\AviShemla\AntiGravity\Nasdaq_Data_All_Sectors_Combined.csv'
output_dir = r'C:\Users\AviShemla\AntiGravity'
champion_ticker = 'GOOG'

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

print("Pivoting and calculating daily % changes...")
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')
returns_df = pivot_df.pct_change()

summary_results = []

for lag in range(1, 6):
    print(f"Analyzing Lag: {lag} days...")
    
    # Target: GOOG at time t
    # Predictors: All stocks at time t-lag
    target = returns_df[champion_ticker].iloc[lag:]
    predictors = returns_df.shift(lag).iloc[lag:]
    
    # Calculate correlations
    # Since we only have one target, we can use corrwith
    corrs = predictors.corrwith(target)
    r2_values = corrs ** 2
    
    # Save to file
    lag_filename = f'GOOG_Lag_{lag}_R2_Analysis.csv'
    lag_path = os.path.join(output_dir, lag_filename)
    r2_values.sort_values(ascending=False).to_csv(lag_path, header=['R2'])
    
    # Get top 5 predictors for summary
    top_5 = r2_values.sort_values(ascending=False).head(5)
    for ticker, val in top_5.items():
        summary_results.append({
            'Lag': lag,
            'Predictor': ticker,
            'R2': val
        })

summary_df = pd.DataFrame(summary_results)
print("\n--- Summary of Top Predictors for GOOG across Lags ---")
print(summary_df.to_string(index=False))
