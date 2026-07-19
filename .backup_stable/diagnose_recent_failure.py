import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.metrics import r2_score, accuracy_score
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

# 1. Load data
print("Loading data...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
champion_ticker = 'JPM'

# We want to compare two targets:
# Target 1: Raw Daily Return %
target_raw = return_pivot[champion_ticker].rename('Target_Raw')
# Target 2: Volatility-Adjusted Return (Daily Return % / STDEV)
target_adj = std_adj_returns[champion_ticker].rename('Target_Adj')

# Use Lag 1 features for this diagnostic
predictors = all_predictors_df.shift(1)

# Combine into one dataframe
data = pd.concat([target_raw, target_adj, predictors], axis=1)

# Drop any columns that are entirely NaN (e.g. Analyst_Consensus)
data = data.dropna(axis=1, how='all')

# Then drop rows with any remaining NaNs
data = data.dropna()

# Split into "History" and "Last 30 Days"
dates = data.index
history = data.iloc[:-30]
last30 = data.iloc[-30:]

print(f"\n--- Period Overview ---")
print(f"History: {history.index.min().date()} to {history.index.max().date()} ({len(history)} days)")
print(f"Last 30: {last30.index.min().date()} to {last30.index.max().date()} ({len(last30)} days)")

# ---------------------------------------------------------
# DIAGNOSTIC 1: Market Regime Shift (Last 30 vs History)
# ---------------------------------------------------------
print("\n--- Diagnostic 1: Market Regime Shift ---")

def summarize_period(df_period, label):
    ret_mean = df_period['Target_Raw'].mean()
    ret_std = df_period['Target_Raw'].std()
    adj_mean = df_period['Target_Adj'].mean()
    adj_std = df_period['Target_Adj'].std()
    vix_mean = df_period['VIX_Close'].mean()
    return pd.Series({
        'Return (Raw) Mean': ret_mean,
        'Return (Raw) Volatility': ret_std,
        'Return (Adj) Mean': adj_mean,
        'Return (Adj) Volatility': adj_std,
        'VIX Mean': vix_mean
    }, name=label)

regime_comp = pd.concat([
    summarize_period(history, 'History'),
    summarize_period(last30, 'Last 30 Days')
], axis=1)
print(regime_comp.round(4).to_string())

# Check correlations with peers
# In the SGP Residual run, the top Lag 1 peers for JPM were:
top_peers = ['BAC_RET_ADJ', 'GS_RET_ADJ', 'MS_RET_ADJ', 'COF_RET_ADJ', 'AMP_RET_ADJ', 'C_RET_ADJ']
available_peers = [p for p in top_peers if p in data.columns]

if available_peers:
    print("\n--- Correlation Breakdown (JPM Target vs Lag 1 Peers) ---")
    corr_hist = history[['Target_Adj'] + available_peers].corr()['Target_Adj'][1:]
    corr_recent = last30[['Target_Adj'] + available_peers].corr()['Target_Adj'][1:]
    corr_comp = pd.DataFrame({'History Corr': corr_hist, 'Last 30 Corr': corr_recent})
    corr_comp['Change'] = corr_comp['Last 30 Corr'] - corr_comp['History Corr']
    print(corr_comp.round(3).to_string())

# ---------------------------------------------------------
# DIAGNOSTIC 2: Target Comparison (Raw vs Adjusted)
# ---------------------------------------------------------
print("\n--- Diagnostic 2: Raw vs Adjusted Target Performance ---")

# Let's use a quick Logistic Regression to test directional accuracy
# (This isolates the feature power from the complex PyMC sampling)

# Features: Top 10 correlated features from history (for Raw)
corr_raw = history.corr()['Target_Raw'].drop(['Target_Raw', 'Target_Adj'])
top_raw_feats = corr_raw.abs().sort_values(ascending=False).head(10).index.tolist()

# Features: Top 10 correlated features from history (for Adj)
corr_adj = history.corr()['Target_Adj'].drop(['Target_Raw', 'Target_Adj'])
top_adj_feats = corr_adj.abs().sort_values(ascending=False).head(10).index.tolist()

# Train/Test arrays
X_train_raw = history[top_raw_feats].values
y_train_raw_dir = (history['Target_Raw'] > 0).astype(int).values
X_test_raw = last30[top_raw_feats].values
y_test_raw_dir = (last30['Target_Raw'] > 0).astype(int).values

X_train_adj = history[top_adj_feats].values
y_train_adj_dir = (history['Target_Adj'] > 0).astype(int).values
X_test_adj = last30[top_adj_feats].values
y_test_adj_dir = (last30['Target_Adj'] > 0).astype(int).values

# Note: Direction of Raw and Adj is usually the same, but the feature sets chosen might differ!
# Standardize
Xm_r = X_train_raw.mean(0); Xs_r = X_train_raw.std(0) + 1e-8
X_train_raw_s = (X_train_raw - Xm_r) / Xs_r; X_test_raw_s = (X_test_raw - Xm_r) / Xs_r

Xm_a = X_train_adj.mean(0); Xs_a = X_train_adj.std(0) + 1e-8
X_train_adj_s = (X_train_adj - Xm_a) / Xs_a; X_test_adj_s = (X_test_adj - Xm_a) / Xs_a

# Model
clf_raw = LogisticRegression(C=1.0, random_state=42).fit(X_train_raw_s, y_train_raw_dir)
pred_raw_hist = clf_raw.predict(X_train_raw_s)
pred_raw_test = clf_raw.predict(X_test_raw_s)

clf_adj = LogisticRegression(C=1.0, random_state=42).fit(X_train_adj_s, y_train_adj_dir)
pred_adj_hist = clf_adj.predict(X_train_adj_s)
pred_adj_test = clf_adj.predict(X_test_adj_s)

print("\nDirectional Accuracy Summary (Logistic Regression baseline):")
print(f"Target: RAW Daily Return %")
print(f"  - History (In-Sample): {accuracy_score(y_train_raw_dir, pred_raw_hist):.1%}")
print(f"  - Last 30 (Out-Sample): {accuracy_score(y_test_raw_dir, pred_raw_test):.1%}")
print(f"  - Top Features: {top_raw_feats[:3]}...")

print(f"\nTarget: ADJ Daily Return (Return/STDEV)")
print(f"  - History (In-Sample): {accuracy_score(y_train_adj_dir, pred_adj_hist):.1%}")
print(f"  - Last 30 (Out-Sample): {accuracy_score(y_test_adj_dir, pred_adj_test):.1%}")
print(f"  - Top Features: {top_adj_feats[:3]}...")

# Plot the regime shift
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
sns.kdeplot(history['Target_Raw'], label='History', ax=axes[0], fill=True, color='steelblue')
sns.kdeplot(last30['Target_Raw'], label='Last 30 Days', ax=axes[0], fill=True, color='salmon')
axes[0].set_title('Distribution of Raw Returns')
axes[0].legend()

sns.kdeplot(history['VIX_Close'], label='History', ax=axes[1], fill=True, color='steelblue')
sns.kdeplot(last30['VIX_Close'], label='Last 30 Days', ax=axes[1], fill=True, color='salmon')
axes[1].set_title('Distribution of VIX')
axes[1].legend()

plt.tight_layout()
plt.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Recent_Failure_Diagnostic.png'))
print("\nSaved diagnostic plot to Recent_Failure_Diagnostic.png")

