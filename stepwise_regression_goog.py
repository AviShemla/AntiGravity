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

# Drop columns with too many NaNs and rows with any NaNs
# Also remove GOOG from predictors
predictors = predictors.drop(columns=[champion_ticker], errors='ignore')
data = pd.concat([target, predictors], axis=1).dropna()

y = data[champion_ticker]
X_pool = data.drop(columns=[champion_ticker])

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
            print(f"Added {best_feature} (p-value: {best_pval:.4f})")
            
        if not changed:
            break
        
        # Cap at 10 features for performance and to avoid overfitting
        if len(included) >= 10:
            break
            
    return included

print(f"Starting Forward Selection for {champion_ticker}...")
selected_features = forward_selection(y, X_pool)

print("\nFinal Model Summary:")
final_model = sm.OLS(y, sm.add_constant(X_pool[selected_features])).fit()
print(final_model.summary())

# Extract key results
results = {
    'R-squared': final_model.rsquared,
    'Adj. R-squared': final_model.rsquared_adj,
    'Features': selected_features
}

print(f"\nFinal Selected Stocks: {', '.join(selected_features)}")
print(f"Combined R-squared: {results['R-squared']:.4f}")
