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

# Define champions based on previous step
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
print(f"Total Unique Champions: {len(unique_champions)}")

all_summaries = []

for champ in unique_champions:
    print(f"\nAnalyzing Sector Champion: {champ}...")
    for lag in range(1, 6):
        target = returns_df[champ].iloc[lag:]
        predictors = returns_df.shift(lag).iloc[lag:]
        
        corrs = predictors.corrwith(target)
        r2_values = corrs ** 2
        
        # Get top 3 predictors for this champ/lag
        # Exclude self-lag only if it's the champ itself
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
summary_output = os.path.join(output_dir, 'Sector_Champions_Lag_Analysis_Summary.csv')
results_df.to_csv(summary_output, index=False)

print("\n--- Top Lagged Predictor for Each Sector Champion (Across all 1-5 lags) ---")
# Show the single best predictor for each champion found across any lag
best_per_champ = results_df.sort_values('R2', ascending=False).groupby('Champion').first()
print(best_per_champ.to_string())

print(f"\nFull results saved to {summary_output}")
