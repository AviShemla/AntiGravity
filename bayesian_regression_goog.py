import pandas as pd
import numpy as np
from sklearn.linear_model import BayesianRidge
import os

input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Nasdaq_Data_All_Sectors_Combined.csv')
champion_ticker = 'GOOG'

print("Reading and prepping data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')
returns_df = pivot_df.pct_change()

# Align Target(t) with Predictors(t-1)
target = returns_df[champion_ticker].iloc[1:]
predictors = returns_df.shift(1).iloc[1:]
predictors = predictors.drop(columns=[champion_ticker], errors='ignore')
data = pd.concat([target, predictors], axis=1).dropna()

# Split into Train (80%) and Test (20%) chronologically
split_idx = int(len(data) * 0.8)
train_data = data.iloc[:split_idx]
test_data = data.iloc[split_idx:]

y_train = train_data[champion_ticker]
X_train = train_data.drop(columns=[champion_ticker])

y_test = test_data[champion_ticker]
X_test = test_data.drop(columns=[champion_ticker])

print(f"Training Bayesian Ridge model on {X_train.shape[0]} samples with {X_train.shape[1]} predictors...")
# Bayesian Ridge will automatically apply shrinkage (regularization)
model = BayesianRidge()
model.fit(X_train, y_train)

# Evaluate
r2_train = model.score(X_train, y_train)
r2_test = model.score(X_test, y_test)

print("\n--- Bayesian Model Performance ---")
print(f"Training R-squared: {r2_train:.4f}")
print(f"Testing (Out-of-Sample) R-squared: {r2_test:.4f}")

# Extract coefficients to see which stocks had the most influence
coef_df = pd.DataFrame({
    'Ticker': X_train.columns,
    'Coefficient': model.coef_
})
coef_df['Abs_Coef'] = coef_df['Coefficient'].abs()
top_influencers = coef_df.sort_values('Abs_Coef', ascending=False).head(10)

print("\nTop 10 Influential Stocks in Bayesian Model:")
print(top_influencers[['Ticker', 'Coefficient']].to_string(index=False))

# Plot performance
import matplotlib.pyplot as plt
y_pred_test = model.predict(X_test)
plt.figure(figsize=(12, 6))
plt.plot(y_test.index, y_test.values, label='Actual Returns', alpha=0.5)
plt.plot(y_test.index, y_pred_test, label='Bayesian Prediction', color='green', linewidth=2)
plt.title(f'GOOG Bayesian Prediction vs Actual (Out-of-Sample)')
plt.legend()
plt.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bayesian_test_performance.png'))
print(f"\nBayesian performance plot saved.")
