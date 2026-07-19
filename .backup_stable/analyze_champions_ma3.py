import pandas as pd
import numpy as np
import os

input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Nasdaq_Data_All_Sectors_Combined.csv')
output_dir = os.path.dirname(os.path.abspath(__file__))

print("Reading and prepping data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')
returns_df = pivot_df.pct_change()

# Calculate 3-day Moving Average of daily % changes
print("Calculating 3-day Moving Average for all stocks...")
ma3_returns = returns_df.rolling(window=3).mean()

sector_champions = {
    'Basic_Materials': 'LIN',
    'CommunicationServices': 'META',
    'ConsumerDiscretionary': 'TSLA',
    'Consumer_Staples': 'COST',
    'Energy': 'XOM',
    'Financials': 'MSTR',
    'General': 'PLTR',
    'HealthCare': 'MRNA',
    'Industrials': 'HON',
    'Real_Estate': 'AMT',
    'Utilities': 'NEE'
}

unique_champions = list(set(sector_champions.values()))
all_summaries = []

for champ in unique_champions:
    print(f"\nAnalyzing Champion: {champ} using 3-day MA predictors...")
    for lag in range(1, 6):
        # Target: Daily return at t
        # Predictor: 3-day MA of returns ending at t-lag
        target = returns_df[champ].iloc[lag+3:] # Offset by MA window + lag
        predictors = ma3_returns.shift(lag).iloc[lag+3:]
        
        corrs = predictors.corrwith(target)
        r2_values = corrs ** 2
        
        r2_values_filtered = r2_values.drop(champ, errors='ignore')
        top_3 = r2_values_filtered.sort_values(ascending=False).head(3)
        
        for ticker, val in top_3.items():
            all_summaries.append({
                'Champion': champ,
                'Lag': lag,
                'Predictor': ticker,
                'R2': val
            })

results_df = pd.DataFrame(all_summaries)
summary_output = os.path.join(output_dir, 'Sector_Champions_MA3_Lag_Analysis_Summary.csv')
results_df.to_csv(summary_output, index=False)

print("\n--- Top Lagged MA3 Predictors for Each Sector Champion ---")
best_per_champ = results_df.sort_values('R2', ascending=False).groupby('Champion').first()
print(best_per_champ.to_string())

print(f"\nFull results saved to {summary_output}")
