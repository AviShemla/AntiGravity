import pandas as pd
import numpy as np
import os

input_file = r'C:\Users\AviShemla\AntiGravity\Nasdaq_Data_All_Sectors_Combined.csv'
output_file = r'C:\Users\AviShemla\AntiGravity\Stock_Lagged_R2_Matrix_Price.csv'

print("Reading data...")
df = pd.read_csv(input_file)

# Convert Date and sort
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker'])
df = df.sort_values(['Ticker', 'Date'])

# Pivot to get Tickers as columns and Dates as index
print("Pivoting data (using Close prices)...")
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')

# Handle missing values (forward fill then backward fill)
pivot_df = pivot_df.ffill().bfill()

# Shift and align: Target(t) vs Predictor(t-1)
target_df = pivot_df.iloc[1:]
predictor_df = pivot_df.shift(1).iloc[1:]

tickers = pivot_df.columns

print("Calculating full correlation matrix...")
combined_valid = pd.concat([target_df, predictor_df.add_suffix('_lag')], axis=1)
full_corr = combined_valid.corr()

# Extract relevant quadrant
corr_subset = full_corr.loc[tickers, [t + '_lag' for t in tickers]]
r2_subset = corr_subset ** 2
r2_subset.columns = tickers

print(f"Saving Price-based R^2 matrix to {output_file}...")
r2_subset.to_csv(output_file)

# Print results for the first stock
first_stock = tickers[0]
print(f"\nChampion Stock: {first_stock}")
results = r2_subset.loc[first_stock].sort_values(ascending=False).head(11)
print("Top Predictors (lagged R^2 based on Close price):")
print(results)
