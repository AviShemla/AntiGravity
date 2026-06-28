# =============================================================================
# INTEGRATED BAYESIAN LOGISTIC REGRESSION WORKFLOW (JPM)
# Target: Binary Direction of JPM's Raw Daily Return (1 = UP, 0 = DOWN)
# Features: 
#   - Top 3 Data-Driven Lag-1 Predictors (HLT_RAS, JBHT_RAS, HON_RET_ADJ)
#   - The 12-Month Explicit Causal Chain (DVA_Lag3 -> BSX_Lag2 -> AZO_Lag1)
#   - Sector Regime Indicators (JPM_SEC_REG, JPM_SEC_MOM)
# =============================================================================
import pandas as pd
import numpy as np
import pymc as pm
import os
import sys
import matplotlib.pyplot as plt

sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors

os.environ["PYTENSOR_FLAGS"] = "cxx="

champion_ticker = 'JPM'

print("Loading data...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

# 1. Target Definition (Raw Return)
# 1 if Return > 0 else 0
raw_return = return_pivot[champion_ticker]
target_series = (raw_return > 0).astype(int).rename('Target_JPM_DIR_t')

# 2. Filter Dates (Last 12 Months to match causal chain evaluation)
start_date = pd.to_datetime('2025-05-01')
end_date = raw_return.index.max()

# 3. Construct Features
# Lag 1 Features
shifted_1 = all_predictors_df.shift(1)
feat_1 = shifted_1['HLT_RAS'].rename('HLT_RAS_t-1')
feat_2 = shifted_1['JBHT_RAS'].rename('JBHT_RAS_t-1')
feat_3 = shifted_1['HON_RET_ADJ'].rename('HON_RET_ADJ_t-1')
feat_sec_reg = shifted_1[f'{champion_ticker}_SEC_REG'].rename('JPM_SEC_REG_t-1')
feat_sec_mom = shifted_1[f'{champion_ticker}_SEC_MOM'].rename('JPM_SEC_MOM_t-1')

# Explicit Causal Chain
chain_3 = return_pivot['DVA'].shift(3).rename('DVA_Lag3')
chain_2 = return_pivot['BSX'].shift(2).rename('BSX_Lag2')
chain_1 = return_pivot['AZO'].shift(1).rename('AZO_Lag1')

data = pd.concat([
    target_series, raw_return.rename('Target_JPM_RAW_t'), 
    feat_1, feat_2, feat_3, feat_sec_reg, feat_sec_mom,
    chain_3, chain_2, chain_1
], axis=1)

data = data.loc[(data.index >= start_date) & (data.index <= end_date)].dropna()

print(f"\nConstructed Integrated Dataset: {len(data)} trading days.")

# 4. Train / Test Split
# Use last 30 days for Out-of-Sample honest evaluation
split_idx = len(data) - 30
train_data = data.iloc[:split_idx]
test_data = data.iloc[split_idx:]

feature_cols = [
    'HLT_RAS_t-1', 'JBHT_RAS_t-1', 'HON_RET_ADJ_t-1',
    'JPM_SEC_REG_t-1', 'JPM_SEC_MOM_t-1',
    'DVA_Lag3', 'BSX_Lag2', 'AZO_Lag1'
]

y_train = train_data['Target_JPM_DIR_t'].values
X_train = train_data[feature_cols].values

y_test = test_data['Target_JPM_DIR_t'].values
X_test = test_data[feature_cols].values
raw_return_test = test_data['Target_JPM_RAW_t'].values

# Standardize features
Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
Xt_s = (X_train - Xm) / Xs
Xe_s = (X_test - Xm) / Xs

# 5. Bayesian Logistic Regression Model
print(f"\nTraining Bayesian Logistic Regression on {len(feature_cols)} integrated features...")
with pm.Model() as blr_model:
    # Data containers
    X_data = pm.Data("X", Xt_s)
    
    # Priors
    alpha = pm.Normal("alpha", mu=0, sigma=1)
    # Heavy regularization (sigma=0.5) to prevent overfitting the noisy raw returns
    beta = pm.Normal("beta", mu=0, sigma=0.5, shape=X_train.shape[1])
    
    # Logistic link
    mu = alpha + pm.math.dot(X_data, beta)
    p = pm.Deterministic("p", pm.math.sigmoid(mu))
    
    # Likelihood
    y_obs = pm.Bernoulli("y_obs", p=p, observed=y_train)
    
    # Inference
    trace = pm.sample(draws=1000, tune=1000, chains=4, target_accept=0.9, random_seed=42, progressbar=False)
    
    # Out-of-Sample Prediction
    pm.set_data({"X": Xe_s})
    pp = pm.sample_posterior_predictive(trace, var_names=["p"], progressbar=False)

# 6. Evaluation
p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
y_pred_class = (p_pred > 0.5).astype(int)

dir_acc = np.mean(y_pred_class == y_test)

# Scorecard
sc = pd.DataFrame({
    'Raw_Return_%': raw_return_test,
    'Prob_UP': p_pred,
    'Actual_Dir': np.where(y_test == 1, 'UP', 'DOWN'),
    'Pred_Dir': np.where(y_pred_class == 1, 'BUY', 'SELL'),
    'Hit': np.where(y_test == y_pred_class, 'On Target', 'Miss')
}, index=test_data.index)

print(f"\n=== INTEGRATED BLR RESULTS (JPM) ===")
print(f"Test Set Size:   {len(y_test)} days")
print(f"Target:          Binary Direction of Raw Daily Return %")
print(f"Features:        {feature_cols}")
print(f"Directional Acc: {dir_acc:.1%}")

print("\n=== Honest Out-of-Sample Scorecard ===")
print(sc.to_string())

# Plot Beta Posteriors to see what the model actually cared about
import arviz as az
az.plot_forest(trace, var_names=["beta"], combined=True, figsize=(10, 6))
# Annotate feature names
plt.yticks(ticks=np.arange(len(feature_cols)), labels=feature_cols[::-1])
plt.title("Feature Importance (Posterior Weights)")
plt.axvline(0, color='red', linestyle='--')
plt.tight_layout()
plt.savefig(r'C:\Users\AviShemla\AntiGravity\financial_data\JPM_Integrated_BLR_Weights.png')
print("\nSaved feature weights plot to JPM_Integrated_BLR_Weights.png")
