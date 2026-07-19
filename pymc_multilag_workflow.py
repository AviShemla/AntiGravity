import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import os

# Set PyTensor flag to avoid warnings spamming the output
os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Nasdaq_Data_All_Sectors_Combined.csv')
champion_ticker = 'GOOG'

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')

returns_df = pivot_df.pct_change()
ma3_returns = returns_df.rolling(window=3).mean()

def run_pymc_experiment(target_series, all_predictors_df, lag, exp_name):
    print(f"\n--- Starting {exp_name} (Lag {lag}) ---")
    
    # Align data: remove champion from predictors to avoid duplicate columns
    predictors = all_predictors_df.drop(columns=[champion_ticker], errors='ignore').shift(lag)
    data = pd.concat([target_series, predictors], axis=1).dropna()
    
    # Target and Predictor pool
    y_full = data[champion_ticker].values
    X_pool_full = data.drop(columns=[champion_ticker], errors='ignore')
    
    # Split
    split_idx = int(len(data) * 0.8)
    y_train = y_full[:split_idx]
    X_pool_train = X_pool_full.iloc[:split_idx]
    y_test = y_full[split_idx:]
    X_pool_test = X_pool_full.iloc[split_idx:]
    
    # Feature Selection: Pick top 5 based on absolute correlation to keep PyMC fast
    corrs = X_pool_train.corrwith(pd.Series(y_train, index=X_pool_train.index))
    top_5_tickers = corrs.abs().sort_values(ascending=False).head(5).index.tolist()
    print(f"Top 5 predictors selected for PyMC: {top_5_tickers}")
    
    X_train = X_pool_train[top_5_tickers].values
    X_test = X_pool_test[top_5_tickers].values
    
    with pm.Model() as model:
        alpha = pm.Normal("alpha", mu=0, sigma=0.01)
        beta = pm.Normal("beta", mu=0, sigma=0.01, shape=len(top_5_tickers))
        sigma = pm.Exponential("sigma", lam=100)
        
        mu = alpha + pm.math.dot(X_train, beta)
        y_obs = pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y_train)
        
        # Fast sampling for this loop
        trace = pm.sample(draws=500, tune=500, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
    
    # Out-of-sample prediction
    posterior_samples = az.extract(trace)
    alpha_post = posterior_samples.alpha.mean().values
    beta_post = posterior_samples.beta.mean(axis=1).values
    
    y_pred_test = alpha_post + np.dot(X_test, beta_post)
    
    y_test_mean = y_test.mean()
    ss_res = np.sum((y_test - y_pred_test) ** 2)
    ss_tot = np.sum((y_test - y_test_mean) ** 2)
    r2_test = 1 - (ss_res / ss_tot)
    
    print(f"Finished {exp_name} (Lag {lag}) -> Out-of-Sample R2: {r2_test:.4f}")
    return {'Experiment': exp_name, 'Lag': lag, 'Test R2': r2_test, 'Predictors': ", ".join(top_5_tickers)}

if __name__ == '__main__':
    results = []
    
    # Part 1: Daily Returns Lag 1, 2, 3
    for l in [1, 2, 3]:
        res = run_pymc_experiment(returns_df[champion_ticker], returns_df, l, "Daily Returns")
        results.append(res)
        
    # Part 2: MA3 Returns Lag 1, 2, 3
    for l in [1, 2, 3]:
        res = run_pymc_experiment(returns_df[champion_ticker], ma3_returns, l, "MA3 Returns")
        results.append(res)
        
    summary_df = pd.DataFrame(results)
    print("\n\n=== Final PyMC Workflow Summary ===")
    print(summary_df.to_string(index=False))
    
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PyMC_Workflow_MultiLag_Results.csv')
    summary_df.to_csv(out_path, index=False)
