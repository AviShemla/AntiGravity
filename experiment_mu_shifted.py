import pandas as pd
import numpy as np
import pymc as pm
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

os.environ["PYTENSOR_FLAGS"] = "cxx="

ticker = 'MU'
yyy = 'IT'
zzz = 'AAPL'
xxx = 'JKHY'

print(f"Loading data for {ticker} (Historical Test: 2024-06-01 to 2025-07-15)...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
shifted_preds = all_predictors_df.shift(1)

train_start = pd.to_datetime('2024-06-01')
train_end = pd.to_datetime('2025-06-01')
# Test is the first 30 trading days after train_end
returns_df = return_pivot.loc[(return_pivot.index >= train_start)]

print(f"\nEvaluating PyMC BLR on {ticker}")
print(f"Training Window: {train_start.date()} to {train_end.date()}")
print(f"Causal Chain: {yyy} -> {zzz} -> {xxx}")

target_t = returns_df[ticker].rename('Target_t')

# 1. Technical Features (evaluate correlations ONLY on training data to prevent lookahead bias)
comb = pd.concat([target_t, shifted_preds], axis=1).loc[train_start:train_end].dropna(how='all', axis=1).dropna(subset=['Target_t'])
corrs = comb.drop('Target_t', axis=1).corrwith(comb['Target_t'])
tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()
print(f"Top 3 Technicals (Learned from 2024-2025 window): {top_3_tech}")

# 2. Causal Chain & Regime
chain_3 = returns_df[yyy].shift(3).rename(f'{yyy}_Lag3')
chain_2 = returns_df[zzz].shift(2).rename(f'{zzz}_Lag2')
chain_1 = returns_df[xxx].shift(1).rename(f'{xxx}_Lag1')

feat_cols = top_3_tech + [chain_3.name, chain_2.name, chain_1.name]

components = [
    (target_t > 0).astype(int).rename('Target_DIR'),
    shifted_preds[top_3_tech],
    chain_3, chain_2, chain_1
]

sec_reg_name = f'{ticker}_SEC_REG'
sec_mom_name = f'{ticker}_SEC_MOM'

if sec_reg_name in shifted_preds.columns:
    components.append(shifted_preds[sec_reg_name].rename(f'{sec_reg_name}_t-1'))
    feat_cols.append(f'{sec_reg_name}_t-1')
if sec_mom_name in shifted_preds.columns:
    components.append(shifted_preds[sec_mom_name].rename(f'{sec_mom_name}_t-1'))
    feat_cols.append(f'{sec_mom_name}_t-1')
    
data = pd.concat(components, axis=1).dropna()

# 3. Train/Test Split based on Exact Dates
train_data = data.loc[(data.index >= train_start) & (data.index < train_end)]
test_pool = data.loc[data.index >= train_end]
test_data = test_pool.head(30) # Take exactly 30 days of OOS data

X_train = train_data[feat_cols].values
y_train = train_data['Target_DIR'].values
X_test = test_data[feat_cols].values
y_test = test_data['Target_DIR'].values

Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
X_train_s = (X_train - Xm) / Xs
X_test_s = (X_test - Xm) / Xs

print(f"\nTraining on {len(train_data)} days...")
print(f"Testing on {len(test_data)} days (From {test_data.index.min().date()} to {test_data.index.max().date()})...")

# 4. PyMC Bayesian Logistic Regression
with pm.Model() as blr_model:
    X_data = pm.Data("X", X_train_s)
    alpha = pm.Normal("alpha", mu=0, sigma=1)
    beta = pm.Normal("beta", mu=0, sigma=0.5, shape=X_train_s.shape[1])
    mu = alpha + pm.math.dot(X_data, beta)
    p = pm.Deterministic("p", pm.math.sigmoid(mu))
    pm.Bernoulli("y_obs", p=p, observed=y_train)
    
    trace = pm.sample(draws=1000, tune=1000, chains=4, target_accept=0.9, random_seed=42, progressbar=False)
    
    pm.set_data({"X": X_test_s})
    pp = pm.sample_posterior_predictive(trace, var_names=["p"], progressbar=False)
    
p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
y_pred_class = (p_pred > 0.5).astype(int)

# Calculate confidence metrics (using the strict 65% boundary)
confidence = np.where(p_pred > 0.5, p_pred, 1 - p_pred)
high_conf_idx = confidence > 0.65

dir_acc = np.mean(y_pred_class == y_test)

if np.sum(high_conf_idx) > 0:
    high_conf_acc = np.mean(y_pred_class[high_conf_idx] == y_test[high_conf_idx])
else:
    high_conf_acc = np.nan
    
print(f"\n=== RESULTS FOR {ticker} (SHIFTED 1 YEAR INTO THE PAST) ===")
print(f"Overall OOS Accuracy: {dir_acc:.1%}")
print(f"High-Confidence (>65%) Acc: {high_conf_acc*100:.1f}%")
print(f"High-Confidence Trades: {np.sum(high_conf_idx)}")
