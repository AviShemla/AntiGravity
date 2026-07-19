# =============================================================================
# SGP CAUSAL CHAIN WORKFLOW
# Target: TGT (Raw Daily Return)
# Predictors: Explicit 3-day causal chain found via discovery algorithm:
#   - Lag 3: BIO (Bio-Rad Laboratories)
#   - Lag 2: IDXX (IDEXX Laboratories)
#   - Lag 1: IT (Gartner)
# Dataset: 2025-04-30 to 2026-04-30
# =============================================================================
import pandas as pd
import numpy as np
import pymc as pm
import os
import sys
from sklearn.cluster import KMeans
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

os.environ["PYTENSOR_FLAGS"] = "cxx="

champion_ticker = 'TGT'

# 1. Load Data
print("Loading data...")
_, return_pivot, _, _, _ = load_predictors()

# 2. Filter Dates
start_date = pd.to_datetime('2026-01-30')
end_date = pd.to_datetime('2026-04-30')
returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)]

# 3. Construct the explicit Causal Chain Features
target_series = returns_df[champion_ticker].rename('Target_TGT_t')
lag1_feature = returns_df['NOC'].shift(1).rename('Lag1_NOC_t-1')
lag2_feature = returns_df['PSKY'].shift(2).rename('Lag2_PSKY_t-2')
lag3_feature = returns_df['HUM'].shift(3).rename('Lag3_HUM_t-3')

# Combine and drop NaNs created by shifting
data = pd.concat([target_series, lag1_feature, lag2_feature, lag3_feature], axis=1).dropna()

print(f"\nConstructed Causal Chain Dataset: {len(data)} trading days.")

# 4. Train / Test Split
# We only have ~60 days, so let's use the last 15 days as out-of-sample
split_idx = len(data) - 15
train_data = data.iloc[:split_idx]
test_data = data.iloc[split_idx:]

y_train = train_data['Target_TGT_t'].values
X_train = train_data[['Lag1_NOC_t-1', 'Lag2_PSKY_t-2', 'Lag3_HUM_t-3']].values

y_test = test_data['Target_TGT_t'].values
X_test = test_data[['Lag1_NOC_t-1', 'Lag2_PSKY_t-2', 'Lag3_HUM_t-3']].values

# Standardize features
Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
Xt_s = (X_train - Xm) / Xs
Xe_s = (X_test - Xm) / Xs

# Standardize target for the GP to help sampling
ym = y_train.mean(); ys = y_train.std() + 1e-8
y_train_s = (y_train - ym) / ys

# 5. PyMC Sparse GP Model
print("\nTraining Sparse GP on causal chain features...")
with pm.Model() as model:
    # 3 features -> shape=3
    ls = pm.Gamma("ls", alpha=2, beta=1, shape=3)
    eta = pm.HalfNormal("eta", sigma=1.0)
    cov = eta**2 * pm.gp.cov.ExpQuad(input_dim=3, ls=ls)
    
    # We only have ~45 train points, so 25 inducing points is plenty
    Xu = KMeans(n_clusters=min(25, len(Xt_s)), random_state=42, n_init=5).fit(Xt_s).cluster_centers_
    gp = pm.gp.MarginalApprox(cov_func=cov, approx="FITC")
    
    sigma = pm.HalfNormal("sigma", sigma=1.0)
    y_obs = gp.marginal_likelihood("y_obs", X=Xt_s, Xu=Xu, y=y_train_s, sigma=sigma)
    
    trace = pm.sample(draws=300, tune=300, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
    
    # Predict on test set
    f_pred = gp.conditional("f_pred", Xnew=Xe_s)
    pp = pm.sample_posterior_predictive(trace, var_names=["f_pred"], progressbar=False)

# Re-scale predictions back to raw return space
y_pred_s = pp.posterior_predictive["f_pred"].mean(dim=["chain", "draw"]).values
y_pred = (y_pred_s * ys) + ym

# 6. Evaluation
ss_res = np.sum((y_test - y_pred)**2)
ss_tot = np.sum((y_test - y_test.mean())**2)
r2 = 1 - ss_res / ss_tot if ss_tot != 0 else np.nan

dir_acc = np.mean(np.sign(y_pred) == np.sign(y_test))

print(f"\n=== SGP CAUSAL CHAIN RESULTS ({champion_ticker}) ===")
print(f"Test Set Size:   {len(y_test)} days")
print(f"Target:          Raw Daily Return %")
print(f"Features:        Lag3_BIO, Lag2_IDXX, Lag1_IT")
print(f"Out-of-Sample R²:{r2:.4f}")
print(f"Directional Acc: {dir_acc:.1%}")

# Scorecard
sc = pd.DataFrame({
    'Actual_Return': y_test,
    'Pred_Return': y_pred,
    'Actual_Dir': np.where(y_test > 0, 'UP', 'Down'),
    'Pred_Dir': np.where(y_pred > 0, 'BUY', 'SELL'),
    'Hit': np.where(np.sign(y_test) == np.sign(y_pred), 'On Target', 'Miss')
}, index=test_data.index)

print("\n=== Out-of-Sample Scorecard ===")
print(sc.to_string())

# Plot
plt.figure(figsize=(12, 6))
plt.plot(sc.index, sc['Actual_Return'], label='Actual TGT Return', color='steelblue', alpha=0.7)
plt.plot(sc.index, sc['Pred_Return'], label=f'Predicted (R²={r2:.3f})', color='darkorange', linewidth=2)
plt.axhline(0, color='black', linestyle='--', linewidth=1)
plt.title(f"{champion_ticker} Prediction using Causal Chain (BIO t-3 -> IDXX t-2 -> IT t-1)")
plt.ylabel("Raw Daily Return %")
plt.legend()
plt.grid(alpha=0.3)
plt.tight_layout()
plot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'TGT_Causal_Chain_Plot.png')
plt.savefig(plot_path, dpi=300)
print(f"\nPlot saved to {plot_path}")
