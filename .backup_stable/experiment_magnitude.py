import pandas as pd
import numpy as np
import pymc as pm
import matplotlib.pyplot as plt
import seaborn as sns
import os
import sys

# Suppress PyTensor compiler warnings
os.environ["PYTENSOR_FLAGS"] = "cxx="

sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors

print("Loading data for Magnitude Prediction Experiment...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

portfolio = pd.read_csv(r'C:\Users\AviShemla\AntiGravity\financial_data\Active_Portfolio.csv')
target_ticker = 'TSLA' # We'll use TSLA since it's volatile and great for magnitude tests

row = portfolio[portfolio['Ticker'] == target_ticker].iloc[0]
depth = int(row['Depth'])
lags_dict = {d: row[f'Lag{d}'] for d in range(depth, 0, -1)}

print(f"Target: {target_ticker}")
print(f"Lags: {lags_dict}")

start_date = pd.to_datetime('2025-05-01')
end_date = return_pivot.index.max()

returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)]
shifted_preds = all_predictors_df.shift(1)

# Build features
target_t = returns_df[target_ticker].rename('Target_t')
target_dir = (target_t > 0).astype(float).rename('Target_DIR')

comb = pd.concat([target_t, shifted_preds], axis=1).loc[start_date:end_date].dropna(how='all', axis=1)
hist_comb = comb.dropna(subset=['Target_t'])
corrs = hist_comb.drop('Target_t', axis=1).corrwith(hist_comb['Target_t'])
tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()

feat_cols = top_3_tech.copy()
components = [
    target_dir,
    target_t.rename('Raw_Return_%'),
    shifted_preds[top_3_tech]
]

for d in range(depth, 0, -1):
    lag_name = lags_dict[d]
    chain_col = returns_df[lag_name].shift(d).rename(f'{lag_name}_Lag{d}')
    components.append(chain_col)
    feat_cols.append(chain_col.name)

sec_reg_name = f'{target_ticker}_SEC_REG'
sec_mom_name = f'{target_ticker}_SEC_MOM'
if sec_reg_name in shifted_preds.columns:
    components.append(shifted_preds[sec_reg_name].rename(f'{sec_reg_name}_t-1'))
    feat_cols.append(f'{sec_reg_name}_t-1')
if sec_mom_name in shifted_preds.columns:
    components.append(shifted_preds[sec_mom_name].rename(f'{sec_mom_name}_t-1'))
    feat_cols.append(f'{sec_mom_name}_t-1')

data_with_future = pd.concat(components, axis=1).loc[start_date:end_date]
data_with_future = data_with_future.dropna(subset=feat_cols)
data_clean = data_with_future.dropna(subset=['Target_DIR', 'Raw_Return_%'])

print(f"Features: {feat_cols}")
print(f"Total trading days available: {len(data_clean)}")

# Train/Test Split (Last 40 days for testing)
split_idx = len(data_clean) - 40
train_data = data_clean.iloc[:split_idx]
test_data = data_clean.iloc[split_idx:]

X_train = train_data[feat_cols].values
y_dir_train = train_data['Target_DIR'].values
y_mag_train = train_data['Raw_Return_%'].values

X_test = test_data[feat_cols].values
y_dir_test = test_data['Target_DIR'].values
y_mag_test = test_data['Raw_Return_%'].values

# Standardize
Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
X_train_s = (X_train - Xm) / Xs
X_test_s = (X_test - Xm) / Xs

print("\nBuilding Dual-Head Bayesian Model...")
with pm.Model() as dual_head_model:
    X_data = pm.Data("X", X_train_s)
    
    # Shared weights (We can use the same linear combination for both, or separate. Let's use separate weights for flexibility)
    # Direction Head
    alpha_dir = pm.Normal("alpha_dir", mu=0, sigma=1)
    beta_dir = pm.Normal("beta_dir", mu=0, sigma=0.5, shape=X_train_s.shape[1])
    mu_dir = alpha_dir + pm.math.dot(X_data, beta_dir)
    p = pm.Deterministic("p", pm.math.sigmoid(mu_dir))
    pm.Bernoulli("y_obs_dir", p=p, observed=y_dir_train, shape=X_data.shape[0])
    
    # Magnitude Head
    alpha_mag = pm.Normal("alpha_mag", mu=0, sigma=2)
    beta_mag = pm.Normal("beta_mag", mu=0, sigma=1, shape=X_train_s.shape[1])
    mu_mag = alpha_mag + pm.math.dot(X_data, beta_mag)
    
    # Error variance (volatility)
    sigma_mag = pm.HalfNormal("sigma_mag", sigma=3)
    
    pm.Normal("y_obs_mag", mu=mu_mag, sigma=sigma_mag, observed=y_mag_train, shape=X_data.shape[0])

    print("Sampling...")
    trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, random_seed=42, progressbar=True)
    
    print("Posterior Predictive...")
    pm.set_data({"X": X_test_s})
    pp = pm.sample_posterior_predictive(trace, var_names=["p", "y_obs_mag"], progressbar=False)

p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
mag_pred_mean = pp.posterior_predictive["y_obs_mag"].mean(dim=["chain", "draw"]).values
mag_pred_std = pp.posterior_predictive["y_obs_mag"].std(dim=["chain", "draw"]).values

results = pd.DataFrame({
    'Date': test_data.index,
    'P_UP': p_pred,
    'Expected_Return_%': mag_pred_mean,
    'Expected_Volatility_%': mag_pred_std,
    'Actual_Return_%': y_mag_test
})

# Filter high confidence predictions (P > 0.65 or P < 0.35)
high_conf = results[(results['P_UP'] > 0.65) | (results['P_UP'] < 0.35)].copy()
high_conf['Predicted_Dir'] = np.where(high_conf['P_UP'] > 0.5, 1, -1)
high_conf['Actual_Dir'] = np.where(high_conf['Actual_Return_%'] > 0, 1, -1)
high_conf['Direction_Hit'] = high_conf['Predicted_Dir'] == high_conf['Actual_Dir']

print("\n=== High Confidence Predictions ===")
print(high_conf.to_string())
print(f"Directional Hit Rate: {high_conf['Direction_Hit'].mean() * 100:.1f}%")

# Plotting
artifact_dir = r"C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c"
plot_path = os.path.join(artifact_dir, "magnitude_experiment_plot.png")

plt.figure(figsize=(12, 6))

# Scatter Plot
plt.subplot(1, 2, 1)
plt.scatter(high_conf['Expected_Return_%'], high_conf['Actual_Return_%'], c=high_conf['Direction_Hit'].map({True: 'green', False: 'red'}), s=100, alpha=0.7)
plt.axhline(0, color='black', linestyle='--')
plt.axvline(0, color='black', linestyle='--')

# Fit a line
m, b = np.polyfit(high_conf['Expected_Return_%'], high_conf['Actual_Return_%'], 1)
plt.plot(high_conf['Expected_Return_%'], m*high_conf['Expected_Return_%'] + b, color='blue', alpha=0.5, label='Trend')

plt.title("Expected vs Actual Return (High Conf)")
plt.xlabel("Model Expected Return (%)")
plt.ylabel("Actual Return (%)")
plt.grid(True, alpha=0.3)
plt.legend()

# Error bars for magnitude
plt.subplot(1, 2, 2)
high_conf = high_conf.sort_values('Date')
x_idx = np.arange(len(high_conf))
plt.errorbar(x_idx, high_conf['Expected_Return_%'], yerr=high_conf['Expected_Volatility_%'], fmt='o', color='blue', label='Expected Return ± 1 StdDev', capsize=5)
plt.scatter(x_idx, high_conf['Actual_Return_%'], color='red', label='Actual Return', zorder=5, s=50, marker='x')
plt.axhline(0, color='black', linestyle='--')
plt.xticks(x_idx, high_conf['Date'].dt.strftime('%m-%d'), rotation=45)
plt.title("Predicted Bounds vs Actual Outcome")
plt.ylabel("Return (%)")
plt.legend()
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(plot_path)
print(f"\nPlot saved to {plot_path}")
