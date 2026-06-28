import pandas as pd
import numpy as np
from sklearn.linear_model import BayesianRidge
import os

input_file = r'C:\Users\AviShemla\AntiGravity\Nasdaq_Data_All_Sectors_Combined.csv'
champion_ticker = 'LIN'

print("Reading and prepping data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')
returns_df = pivot_df.pct_change()
ma3_returns = returns_df.rolling(window=3).mean()

def run_bayesian_experiment(target_series, predictor_df, lag, name):
    # Align
    data = pd.concat([target_series, predictor_df.shift(lag)], axis=1).dropna()
    
    # Split
    split_idx = int(len(data) * 0.8)
    train_data = data.iloc[:split_idx]
    test_data = data.iloc[split_idx:]
    
    y_train = train_data[champion_ticker]
    X_train = train_data.drop(columns=[champion_ticker])
    y_test = test_data[champion_ticker]
    X_test = test_data.drop(columns=[champion_ticker])
    
    # Fit
    model = BayesianRidge()
    model.fit(X_train, y_train)
    
    # Score
    r2_train = model.score(X_train, y_train)
    r2_test = model.score(X_test, y_test)
    
    return {'Experiment': name, 'Lag': lag, 'Train R2': r2_train, 'Test R2': r2_test}

results = []

# Experiments with Daily Returns
for lag in [1, 2, 3]:
    res = run_bayesian_experiment(returns_df[champion_ticker], 
                                  returns_df.drop(columns=[champion_ticker], errors='ignore'), 
                                  lag, "Daily Returns")
    results.append(res)

# Experiments with MA3 Returns
for lag in [1, 2, 3]:
    res = run_bayesian_experiment(returns_df[champion_ticker], 
                                  ma3_returns.drop(columns=[champion_ticker], errors='ignore'), 
                                  lag, "MA3 Returns")
    results.append(res)

summary_df = pd.DataFrame(results)
print("\n--- Bayesian Analysis Multi-Lag & MA3 Summary ---")
print(summary_df.to_string(index=False))

output_path = os.path.join(r'C:\Users\AviShemla\AntiGravity', 'Bayesian_MultiLag_Analysis_LIN.csv')
summary_df.to_csv(output_path, index=False)
print(f"\nFull results saved to {output_path}")
