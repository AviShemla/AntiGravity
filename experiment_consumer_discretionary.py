import pandas as pd
import numpy as np
import pymc as pm
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

os.environ["PYTENSOR_FLAGS"] = "cxx="

champion_ticker = 'HD'

print(f"Loading data for Consumer Discretionary ticker: {champion_ticker}...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

start_date = pd.to_datetime('2025-05-01')
end_date = return_pivot.index.max()

# --- PART 1: DISCOVER CAUSAL CHAIN ---
print(f"\n[Part 1] Discovering 12-Month Causal Chain for {champion_ticker}...")
returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)].dropna(axis=1, how='all')

def find_best_lag1(target_series, predictor_df):
    shifted = predictor_df.shift(1)
    combined = pd.concat([target_series.rename('Target'), shifted], axis=1).dropna()
    if len(combined) < 50: return None
    corrs = combined.drop('Target', axis=1).corrwith(combined['Target'])
    return corrs.abs().idxmax()

# Find Lag 1 peer
xxx = find_best_lag1(returns_df[champion_ticker], returns_df)
# Find Lag 2 bridge
zzz = find_best_lag1(returns_df[xxx], returns_df)
# Find Lag 3 leader
yyy = find_best_lag1(returns_df[zzz], returns_df)

print(f"Discovered Chain: {yyy} (Lag 3) -> {zzz} (Lag 2) -> {xxx} (Lag 1) -> {champion_ticker}")

# --- PART 2: FIND TOP TECHNICALS ---
print("\n[Part 2] Finding Top Technical Predictors...")
target_t = return_pivot[champion_ticker].rename('Target_t')
shifted_preds = all_predictors_df.shift(1)
comb = pd.concat([target_t, shifted_preds], axis=1).loc[start_date:end_date].dropna(how='all', axis=1).dropna(subset=['Target_t'])
corrs = comb.drop('Target_t', axis=1).corrwith(comb['Target_t'])
# Filter out macro and sector to isolate pure technicals
tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()
print(f"Top 3 Technicals: {top_3_tech}")

# --- PART 3: INTEGRATED DATASET ---
feat_sec_reg = shifted_preds[f'{champion_ticker}_SEC_REG'].rename(f'{champion_ticker}_SEC_REG_t-1')
feat_sec_mom = shifted_preds[f'{champion_ticker}_SEC_MOM'].rename(f'{champion_ticker}_SEC_MOM_t-1')
chain_3 = return_pivot[yyy].shift(3).rename(f'{yyy}_Lag3')
chain_2 = return_pivot[zzz].shift(2).rename(f'{zzz}_Lag2')
chain_1 = return_pivot[xxx].shift(1).rename(f'{xxx}_Lag1')

data = pd.concat([
    (target_t > 0).astype(int).rename('Target_DIR'), 
    target_t.rename('Target_RAW'), 
    shifted_preds[top_3_tech], 
    feat_sec_reg, feat_sec_mom,
    chain_3, chain_2, chain_1
], axis=1).loc[start_date:end_date].dropna()

split_idx = len(data) - 30
train_data = data.iloc[:split_idx]
test_data = data.iloc[split_idx:]

feature_cols = top_3_tech + [f'{champion_ticker}_SEC_REG_t-1', f'{champion_ticker}_SEC_MOM_t-1', f'{yyy}_Lag3', f'{zzz}_Lag2', f'{xxx}_Lag1']

X_train = train_data[feature_cols].values
y_train = train_data['Target_DIR'].values
X_test = test_data[feature_cols].values
y_test = test_data['Target_DIR'].values
raw_return_test = test_data['Target_RAW'].values

Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
Xt_s = (X_train - Xm) / Xs
Xe_s = (X_test - Xm) / Xs

# --- PART 4: TRAIN BLR ---
print(f"\n[Part 4] Training Bayesian Logistic Regression on {len(feature_cols)} features...")
with pm.Model() as blr_model:
    X_data = pm.Data("X", Xt_s)
    alpha = pm.Normal("alpha", mu=0, sigma=1)
    beta = pm.Normal("beta", mu=0, sigma=0.5, shape=X_train.shape[1])
    mu = alpha + pm.math.dot(X_data, beta)
    p = pm.Deterministic("p", pm.math.sigmoid(mu))
    y_obs = pm.Bernoulli("y_obs", p=p, observed=y_train)
    trace = pm.sample(draws=1000, tune=1000, chains=4, target_accept=0.9, random_seed=42, progressbar=False)
    pm.set_data({"X": Xe_s})
    pp = pm.sample_posterior_predictive(trace, var_names=["p"], progressbar=False)

p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
y_pred_class = (p_pred > 0.5).astype(int)
dir_acc = np.mean(y_pred_class == y_test)

print(f"\n=== INTEGRATED BLR RESULTS ({champion_ticker}) ===")
print(f"Test Set Size:   {len(y_test)} days")
print(f"Features:        {feature_cols}")
print(f"Directional Acc: {dir_acc:.1%}")

sc = pd.DataFrame({
    'Raw_Return_%': raw_return_test,
    'Prob_UP': p_pred,
    'Actual_Dir': np.where(y_test == 1, 'UP', 'DOWN'),
    'Pred_Dir': np.where(y_pred_class == 1, 'BUY', 'SELL'),
    'Hit': np.where(y_test == y_pred_class, 'On Target', 'Miss')
}, index=test_data.index)
print("\n=== Honest Out-of-Sample Scorecard ===")
print(sc.to_string())
