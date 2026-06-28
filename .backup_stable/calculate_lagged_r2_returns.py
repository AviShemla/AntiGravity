import pandas as pd
import numpy as np
import os

input_file = r'C:\Users\AviShemla\AntiGravity\Nasdaq_Data_All_Sectors_Combined.csv'
output_file = r'C:\Users\AviShemla\AntiGravity\Stock_Lagged_R2_Matrix_Returns.csv'

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

print("Pivoting and calculating daily % changes...")
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')
returns_df = pivot_df.pct_change()

# Shift for Lagged Analysis: Target(t) vs Predictor(t-1)
target_df = returns_df.iloc[1:]
predictor_df = returns_df.shift(1).iloc[1:]

tickers = returns_df.columns

print("Calculating Lagged Correlation Matrix for Returns...")
combined_valid = pd.concat([target_df, predictor_df.add_suffix('_lag')], axis=1).dropna()
full_corr = combined_valid.corr()

# Extract relevant quadrant
corr_subset = full_corr.loc[tickers, [t + '_lag' for t in tickers]]
r2_subset = corr_subset ** 2
r2_subset.columns = tickers

print(f"Saving Returns-based R^2 matrix to {output_file}...")
r2_subset.to_csv(output_file)

# Find top correlations
r2_subset.index.name = 'Target_Stock'
r2_subset.columns.name = 'Predictor_Stock'

stacked = r2_subset.stack().reset_index()
stacked.columns = ['Target', 'Predictor', 'R2']

# Filter out self-correlations and show top
top_pairs = stacked[stacked['Target'] != stacked['Predictor']].sort_values('R2', ascending=False).head(15)

print("\nTop Lagged Predictors (Daily % Change):")
print(top_pairs.to_string(index=False))
