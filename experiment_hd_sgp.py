import pandas as pd
import numpy as np
import pymc as pm
import os
import sys
from sklearn.cluster import KMeans

sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors

os.environ["PYTENSOR_FLAGS"] = "cxx="

champion_ticker = 'HD'

print(f"Loading data for SGP Integrated Workflow on {champion_ticker}...")
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

xxx = find_best_lag1(returns_df[champion_ticker], returns_df)
zzz = find_best_lag1(returns_df[xxx], returns_df)
yyy = find_best_lag1(returns_df[zzz], returns_df)
print(f"Discovered Chain: {yyy} (Lag 3) -> {zzz} (Lag 2) -> {xxx} (Lag 1) -> {champion_ticker}")

# --- PART 2: FIND TOP TECHNICALS ---
target_t = return_pivot[champion_ticker].rename('Target_t')
shifted_preds = all_predictors_df.shift(1)
comb = pd.concat([target_t, shifted_preds], axis=1).loc[start_date:end_date].dropna(how='all', axis=1).dropna(subset=['Target_t'])
corrs = comb.drop('Target_t', axis=1).corrwith(comb['Target_t'])
tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()

# --- PART 3: INTEGRATED DATASET ---
feat_sec_reg = shifted_preds[f'{champion_ticker}_SEC_REG'].rename(f'{champion_ticker}_SEC_REG_t-1')
feat_sec_mom = shifted_preds[f'{champion_ticker}_SEC_MOM'].rename(f'{champion_ticker}_SEC_MOM_t-1')
chain_3 = return_pivot[yyy].shift(3).rename(f'{yyy}_Lag3')
chain_2 = return_pivot[zzz].shift(2).rename(f'{zzz}_Lag2')
chain_1 = return_pivot[xxx].shift(1).rename(f'{xxx}_Lag1')

# For SGP, we predict the continuous raw return directly, not binary DIR
data = pd.concat([
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
y_train = train_data['Target_RAW'].values
X_test = test_data[feature_cols].values
y_test = test_data['Target_RAW'].values

# Standardize features
Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
Xt_s = (X_train - Xm) / Xs
Xe_s = (X_test - Xm) / Xs

# Standardize target for continuous GP prediction
ym = y_train.mean(); ys = y_train.std() + 1e-8
y_train_s = (y_train - ym) / ys

# --- PART 4: TRAIN SPARSE GAUSSIAN PROCESS ---
num_features = len(feature_cols)
print(f"\n[Part 4] Training Sparse Gaussian Process on {num_features} integrated features...")
with pm.Model() as sgp_model:
    # Hyperparameters
    ls = pm.Gamma("ls", alpha=2, beta=1, shape=num_features)
    eta = pm.HalfNormal("eta", sigma=1.0)
    cov = eta**2 * pm.gp.cov.ExpQuad(input_dim=num_features, ls=ls)
    
    # 50 Inducing points via KMeans
    num_inducing = min(50, len(Xt_s))
    Xu = KMeans(n_clusters=num_inducing, random_state=42, n_init=5).fit(Xt_s).cluster_centers_
    
    gp = pm.gp.MarginalApprox(cov_func=cov, approx="FITC")
    
    # Noise model
    sigma = pm.HalfNormal("sigma", sigma=1.0)
    
    # Marginal Likelihood (Continuous)
    y_obs = gp.marginal_likelihood("y_obs", X=Xt_s, Xu=Xu, y=y_train_s, sigma=sigma)
    
    # Sampling
    trace = pm.sample(draws=300, tune=300, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
    
    # Predictive
    f_pred = gp.conditional("f_pred", Xnew=Xe_s)
    pp = pm.sample_posterior_predictive(trace, var_names=["f_pred"], progressbar=False)

# Inverse transform predictions back to raw return %
y_pred_s = pp.posterior_predictive["f_pred"].mean(dim=["chain", "draw"]).values
y_pred = (y_pred_s * ys) + ym

# Evaluation metrics
ss_res = np.sum((y_test - y_pred)**2)
ss_tot = np.sum((y_test - y_test.mean())**2)
r2 = 1 - ss_res / ss_tot if ss_tot != 0 else np.nan

dir_acc = np.mean(np.sign(y_pred) == np.sign(y_test))

print(f"\n=== SGP RESULTS ({champion_ticker}) ===")
print(f"Test Set Size:   {len(y_test)} days")
print(f"Features:        {feature_cols}")
print(f"Out-of-Sample R²:{r2:.4f}")
print(f"Directional Acc: {dir_acc:.1%}")

sc = pd.DataFrame({
    'Actual_Return': y_test,
    'Pred_Return': y_pred,
    'Actual_Dir': np.where(y_test > 0, 'UP', 'DOWN'),
    'Pred_Dir': np.where(y_pred > 0, 'BUY', 'SELL'),
    'Hit': np.where(np.sign(y_test) == np.sign(y_pred), 'On Target', 'Miss')
}, index=test_data.index)

print("\n=== Honest Out-of-Sample Scorecard ===")
print(sc.to_string())
