import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import os
import itertools
import heapq

# Set PyTensor flag to avoid warnings
os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file = r'C:\Users\AviShemla\AntiGravity\Nasdaq_Data_All_Sectors_Combined.csv'
champion_ticker = 'GOOG'

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')

returns_df = pivot_df.pct_change()
ma3_returns = returns_df.rolling(window=3).mean()

def get_top_5_combinations(X, y):
    n_cols = X.shape[1]
    
    y_c = y - np.mean(y)
    y_norm_sq = np.sum(y_c**2)
    
    X_c = X - np.mean(X, axis=0)
    
    C = np.dot(X_c.T, y_c)
    M = np.dot(X_c.T, X_c)
    
    heap = []
    
    for i, j, k in itertools.combinations(range(n_cols), 3):
        num = C[i] + C[j] + C[k]
        denom_sq = M[i,i] + M[j,j] + M[k,k] + 2*(M[i,j] + M[i,k] + M[j,k])
        
        if denom_sq <= 1e-8:
            continue
            
        corr_sq = (num**2) / (denom_sq * y_norm_sq)
        
        if len(heap) < 5:
            heapq.heappush(heap, (corr_sq, (i, j, k)))
        elif corr_sq > heap[0][0]:
            heapq.heapreplace(heap, (corr_sq, (i, j, k)))
            
    top_5 = sorted(heap, key=lambda x: x[0], reverse=True)
    return [item[1] for item in top_5]

def run_pymc_combo_experiment(target_series, all_predictors_df, lag, exp_name):
    print(f"\n--- Starting {exp_name} (Lag {lag}) ---")
    
    # Align data
    predictors = all_predictors_df.drop(columns=[champion_ticker], errors='ignore').shift(lag)
    data = pd.concat([target_series, predictors], axis=1).dropna()
    
    y_full = data[champion_ticker].values
    X_pool_full = data.drop(columns=[champion_ticker], errors='ignore')
    tickers = X_pool_full.columns.tolist()
    
    # Split
    split_idx = int(len(data) * 0.8)
    y_train = y_full[:split_idx]
    X_pool_train = X_pool_full.iloc[:split_idx].values
    y_test = y_full[split_idx:]
    X_pool_test = X_pool_full.iloc[split_idx:].values
    
    # Fast feature selection for combinations
    top_5_triplets = get_top_5_combinations(X_pool_train, y_train)
    
    # Construct the 5 new predictors (averages of the 3 stocks)
    X_train_combos = np.zeros((len(y_train), 5))
    X_test_combos = np.zeros((len(y_test), 5))
    combo_names = []
    
    for idx, (i, j, k) in enumerate(top_5_triplets):
        combo_name = f"{tickers[i]}+{tickers[j]}+{tickers[k]}"
        combo_names.append(combo_name)
        
        X_train_combos[:, idx] = (X_pool_train[:, i] + X_pool_train[:, j] + X_pool_train[:, k]) / 3.0
        X_test_combos[:, idx] = (X_pool_test[:, i] + X_pool_test[:, j] + X_pool_test[:, k]) / 3.0
        
    print(f"Top 5 combinations selected:\n  " + "\n  ".join(combo_names))
    
    with pm.Model() as model:
        alpha = pm.Normal("alpha", mu=0, sigma=0.01)
        beta = pm.Normal("beta", mu=0, sigma=0.01, shape=5)
        sigma = pm.Exponential("sigma", lam=100)
        
        mu = alpha + pm.math.dot(X_train_combos, beta)
        y_obs = pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y_train)
        
        trace = pm.sample(draws=500, tune=500, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
    
    # Out-of-sample prediction
    posterior_samples = az.extract(trace)
    alpha_post = posterior_samples.alpha.mean().values
    beta_post = posterior_samples.beta.mean(axis=1).values
    
    y_pred_test = alpha_post + np.dot(X_test_combos, beta_post)
    
    y_test_mean = y_test.mean()
    ss_res = np.sum((y_test - y_pred_test) ** 2)
    ss_tot = np.sum((y_test - y_test_mean) ** 2)
    r2_test = 1 - (ss_res / ss_tot)
    
    print(f"Finished {exp_name} (Lag {lag}) -> Out-of-Sample R2: {r2_test:.4f}")
    return {'Experiment': exp_name, 'Lag': lag, 'Test R2': r2_test, 'Combinations': " | ".join(combo_names)}

if __name__ == '__main__':
    results = []
    
    for l in [1, 2, 3]:
        res = run_pymc_combo_experiment(returns_df[champion_ticker], returns_df, l, "Daily Returns")
        results.append(res)
        
    for l in [1, 2, 3]:
        res = run_pymc_combo_experiment(returns_df[champion_ticker], ma3_returns, l, "MA3 Returns")
        results.append(res)
        
    summary_df = pd.DataFrame(results)
    print("\n\n=== Final PyMC Combination Workflow Summary ===")
    print(summary_df.to_string(index=False))
    
    out_path = r'C:\Users\AviShemla\AntiGravity\PyMC_Combination_MultiLag_Results.csv'
    summary_df.to_csv(out_path, index=False)
