import pandas as pd
import numpy as np
import pymc as pm
import yfinance as yf
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Suppress warnings for clean output
import warnings
warnings.filterwarnings('ignore')
os.environ["PYTENSOR_FLAGS"] = "cxx="

# Define 10 ETFs to simulate the Prod pipeline load
ETFS_TO_TEST = [
    'XLK', 'XLV', 'XLY', 'XLF', 'XLC', 
    'XLI', 'XLE', 'XLP', 'XLU', 'XLRE'
]

# Provide dummy whales for each ETF just to force the PyMC math to execute
DUMMY_WHALES = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META']

def get_returns(ticker):
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df['Return'] = df['Close'].pct_change()
        return df.dropna()
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def evaluate_fast_pymc_prob(returns_df):
    """Runs the 5-lag PyMC Bayesian model."""
    if returns_df is None or len(returns_df) < 65:
        return 0.5
        
    df = returns_df.copy()
    df['Target_Dir'] = (df['Return'] > 0).astype(int)
    df['Target_Dir_Next'] = df['Target_Dir'].shift(-1)
    for d in range(1, 6):
        df[f'Lag{d}'] = df['Return'].shift(d)
    df = df.dropna().tail(60)
    
    X = df[[f'Lag{d}' for d in range(1, 6)]].values
    y = df['Target_Dir_Next'].values
    
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    # Avoid division by zero
    X_std[X_std == 0] = 1.0
    X_s = (X - X_mean) / X_std
    
    with pm.Model() as model:
        X_data = pm.Data("X", X_s[:-1])
        y_data = pm.Data("y", y[:-1])
        
        alpha = pm.Normal("alpha", mu=0, sigma=1)
        beta = pm.Normal("beta", mu=0, sigma=1, shape=5)
        
        mu = alpha + pm.math.dot(X_data, beta)
        p = pm.Deterministic("p", pm.math.sigmoid(mu))
        pm.Bernoulli("y_obs", p=p, observed=y_data)
        
        trace = pm.sample(draws=300, tune=300, chains=1, progressbar=False, random_seed=42)
        pm.set_data({"X": X_s[[-1]], "y": np.array([0])})
        pp = pm.sample_posterior_predictive(trace, var_names=["p"], progressbar=False)
        
    prob_up = pp.posterior_predictive["p"].mean().item()
    return prob_up

def process_etf_pipeline(target_etf):
    start_t = time.time()
    print(f"[{target_etf}] STARTED Worker Thread.")
    
    # 1. Fetch data and run PyMC for the 5 Whales
    whale_probs = []
    for whale in DUMMY_WHALES:
        ret_df = get_returns(whale)
        prob = evaluate_fast_pymc_prob(ret_df)
        whale_probs.append(prob)
        
    # Aggregate (equal weights for dummy test)
    aggregate_prob = sum(whale_probs) / len(whale_probs)
    whale_prior_mu = (aggregate_prob - 0.5) * 4.0
    
    # 2. Fetch data and run PyMC for the ETF with the Prior injected
    etf_ret = get_returns(target_etf)
    if etf_ret is None or len(etf_ret) < 65:
        print(f"[{target_etf}] FAILED (Data Issue).")
        return False
        
    df = etf_ret.copy()
    df['Target_Dir'] = (df['Return'] > 0).astype(int)
    df['Target_Dir_Next'] = df['Target_Dir'].shift(-1)
    for d in range(1, 6):
        df[f'Lag{d}'] = df['Return'].shift(d)
    df = df.dropna().tail(60)
    
    X = df[[f'Lag{d}' for d in range(1, 6)]].values
    y = df['Target_Dir_Next'].values
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_std[X_std == 0] = 1.0
    X_s = (X - X_mean) / X_std
    
    with pm.Model() as prior_model:
        X_data = pm.Data("X", X_s[:-1])
        y_data = pm.Data("y", y[:-1])
        
        alpha = pm.Normal("alpha", mu=0, sigma=1)
        beta = pm.Normal("beta", mu=0, sigma=1, shape=5)
        whale_prior = pm.Normal("whale_prior", mu=whale_prior_mu, sigma=0.5)
        
        mu = alpha + pm.math.dot(X_data, beta) + whale_prior
        p = pm.Deterministic("p", pm.math.sigmoid(mu))
        pm.Bernoulli("y_obs", p=p, observed=y_data)
        
        trace_prior = pm.sample(draws=300, tune=300, chains=1, progressbar=False, random_seed=42)
        pm.set_data({"X": X_s[[-1]], "y": np.array([0])})
        pp_prior = pm.sample_posterior_predictive(trace_prior, var_names=["p"], progressbar=False)
        prior_prob = pp_prior.posterior_predictive["p"].mean().item()
        
    elapsed = time.time() - start_t
    print(f"[{target_etf}] COMPLETED in {elapsed:.1f} seconds. (P(UP) = {prior_prob*100:.1f}%)")
    return True

if __name__ == "__main__":
    print("=====================================================")
    print(f" PERFORMANCE BENCHMARK: {len(ETFS_TO_TEST)} ETFs * 6 PyMC Models")
    print("=====================================================\n")
    
    global_start = time.time()
    success_count = 0
    
    # We use 3 parallel workers, exactly like the Prod engine compile_etf_scorecards.py
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_etf = {executor.submit(process_etf_pipeline, etf): etf for etf in ETFS_TO_TEST}
        
        for future in as_completed(future_to_etf):
            etf = future_to_etf[future]
            try:
                res = future.result()
                if res:
                    success_count += 1
            except Exception as exc:
                print(f"[{etf}] generated an exception: {exc}")
                
    total_elapsed = time.time() - global_start
    print("\n=====================================================")
    print(f" BENCHMARK COMPLETE!")
    print(f" Total Executed: {success_count} / {len(ETFS_TO_TEST)} ETFs")
    print(f" Total Time Elapsed: {total_elapsed:.1f} seconds ({total_elapsed/60:.1f} minutes)")
    print(f" Average Time per ETF: {total_elapsed / max(1, success_count):.1f} seconds")
    print("=====================================================\n")
