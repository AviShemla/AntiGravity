import pandas as pd
import numpy as np
import statsmodels.api as sm
import os

input_file = r'C:\Users\AviShemla\AntiGravity\Nasdaq_Data_All_Sectors_Combined.csv'
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
X_train_pool = train_data.drop(columns=[champion_ticker])

y_test = test_data[champion_ticker]
X_test_pool = test_data.drop(columns=[champion_ticker])

def forward_selection(y, X_pool, threshold_in=0.05):
    included = []
    while True:
        changed = False
        excluded = list(set(X_pool.columns) - set(included))
        new_pval = pd.Series(index=excluded, dtype=float)
        
        for new_column in excluded:
            model = sm.OLS(y, sm.add_constant(X_pool[included + [new_column]])).fit()
            new_pval[new_column] = model.pvalues[new_column]
        
        best_pval = new_pval.min()
        if best_pval < threshold_in:
            best_feature = new_pval.idxmin()
            included.append(best_feature)
            changed = True
            print(f"  Added {best_feature} (p-value: {best_pval:.4f})")
            
        if not changed or len(included) >= 10:
            break
    return included

print(f"Training model on first {len(train_data)} days...")
selected_features = forward_selection(y_train, X_train_pool)

# Train the final model on training set
X_train_final = sm.add_constant(X_train_pool[selected_features])
final_model = sm.OLS(y_train, X_train_final).fit()

# Evaluate on Training set
r2_train = final_model.rsquared

# Evaluate on Testing set
X_test_final = sm.add_constant(X_test_pool[selected_features])
# Note: sm.add_constant might fail if X_test has fewer columns than selected_features, but here it's fine
y_pred_test = final_model.predict(X_test_final)

# Calculate out-of-sample R-squared
y_test_mean = y_test.mean()
ss_res = ((y_test - y_pred_test) ** 2).sum()
ss_tot = ((y_test - y_test_mean) ** 2).sum()
r2_test = 1 - (ss_res / ss_tot)

print("\n--- Model Performance Summary ---")
print(f"Training R-squared: {r2_train:.4f}")
print(f"Testing (Out-of-Sample) R-squared: {r2_test:.4f}")
print(f"\nPredictors used: {', '.join(selected_features)}")

# Plotting the prediction vs actual for the test set
import matplotlib.pyplot as plt
plt.figure(figsize=(12, 6))
plt.plot(y_test.index, y_test.values, label='Actual Returns', alpha=0.6)
plt.plot(y_test.index, y_pred_test.values, label='Predicted Returns', color='red', linewidth=2)
plt.title(f'GOOG Return Prediction vs Actual (Out-of-Sample Test Set)')
plt.legend()
plt.savefig(r'C:\Users\AviShemla\AntiGravity\regression_test_performance.png')
print(f"Performance plot saved.")
