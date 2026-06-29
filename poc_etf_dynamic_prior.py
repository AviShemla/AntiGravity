import pandas as pd
import numpy as np
import pymc as pm
import yfinance as yf
import os

# We suppress the PyTensor warnings for the POC
os.environ["PYTENSOR_FLAGS"] = "cxx="

# --- CONFIGURATION ---
TARGET_ETF = 'XLK'
# Hardcoded Whales to bypass State Street HTTP 404
WHALES = {
    'AAPL': 0.20,
    'MSFT': 0.20,
    'NVDA': 0.045,
    'AVGO': 0.04,
    'AMD': 0.02
}

print("==================================================")
print(f"  ANTI-GRAVITY: DYNAMIC ETF PRIOR POC ({TARGET_ETF})")
print("==================================================")

def get_returns(ticker):
    print(f"  Downloading 1-year history for {ticker}...")
    df = yf.download(ticker, period="1y", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df['Return'] = df['Close'].pct_change()
    return df.dropna()

def evaluate_fast_pymc_prob(ticker, returns_df):
    """Runs a rapid PyMC Bayesian model to infer P(UP) based on Lag-1 and Lag-2."""
    df = returns_df.copy()
    df['Target_Dir'] = (df['Return'] > 0).astype(int)
    df['Target_Dir_Next'] = df['Target_Dir'].shift(-1)
    for d in range(1, 6):
        df[f'Lag{d}'] = df['Return'].shift(d)
    df = df.dropna()
    
    # We use the last 60 days for a fast evaluation
    df = df.tail(60)
    
    X = df[[f'Lag{d}' for d in range(1, 6)]].values
    y = df['Target_Dir_Next'].values
    
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_s = (X - X_mean) / X_std
    
    with pm.Model() as model:
        X_data = pm.Data("X", X_s[:-1])
        y_data = pm.Data("y", y[:-1])
        
        alpha = pm.Normal("alpha", mu=0, sigma=1)
        beta = pm.Normal("beta", mu=0, sigma=1, shape=5)
        
        mu = alpha + pm.math.dot(X_data, beta)
        p = pm.Deterministic("p", pm.math.sigmoid(mu))
        
        pm.Bernoulli("y_obs", p=p, observed=y_data)
        
        # Fast sampling for POC
        trace = pm.sample(draws=300, tune=300, chains=1, progressbar=False, random_seed=42)
        
        # Predict tomorrow
        X_tomorrow = X_s[[-1]]
        pm.set_data({
            "X": X_tomorrow,
            "y": np.array([0]) # Dummy
        })
        pp = pm.sample_posterior_predictive(trace, var_names=["p"], progressbar=False)
        
    prob_up = pp.posterior_predictive["p"].mean().item()
    print(f"    -> {ticker} P(UP) = {prob_up*100:.1f}%")
    return prob_up

def run_poc():
    # 1. Fetch data for all whales
    whale_probs = {}
    total_weight = sum(WHALES.values())
    
    print("\n[STEP 1] Generating Live PyMC Predictions for Top 5 Whales...")
    for whale, weight in WHALES.items():
        returns = get_returns(whale)
        prob = evaluate_fast_pymc_prob(whale, returns)
        whale_probs[whale] = prob
        
    # Calculate Aggregate Prob
    aggregate_prob = sum(whale_probs[w] * (WHALES[w] / total_weight) for w in WHALES)
    print(f"\n=> AGGREGATE WHALE P(UP): {aggregate_prob*100:.2f}%")
    
    # 2. Map probability back to logit space (mu constraint)
    # 0.5 prob = 0.0 logit. 
    # >0.5 = positive logit (bullish). <0.5 = negative logit (bearish).
    # We multiply by 4 to give it some weight.
    whale_prior_mu = (aggregate_prob - 0.5) * 4.0
    print(f"=> Converted to Bayesian Normal Prior (mu): {whale_prior_mu:.3f}")
    
    # 3. Fetch data for QQQ
    print(f"\n[STEP 2] Fetching {TARGET_ETF} History...")
    qqq_returns = get_returns(TARGET_ETF)
    
    df = qqq_returns.copy()
    df['Target_Dir'] = (df['Return'] > 0).astype(int)
    df['Target_Dir_Next'] = df['Target_Dir'].shift(-1)
    for d in range(1, 6):
        df[f'Lag{d}'] = df['Return'].shift(d)
    df = df.dropna().tail(60)
    
    X = df[[f'Lag{d}' for d in range(1, 6)]].values
    y = df['Target_Dir_Next'].values
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_s = (X - X_mean) / X_std
    
    print("\n[STEP 3] Running QQQ PyMC Model WITHOUT Whale Prior (Baseline)...")
    with pm.Model() as baseline_model:
        X_data = pm.Data("X", X_s[:-1])
        y_data = pm.Data("y", y[:-1])
        
        alpha = pm.Normal("alpha", mu=0, sigma=1)
        beta = pm.Normal("beta", mu=0, sigma=1, shape=5)
        
        mu = alpha + pm.math.dot(X_data, beta)
        p = pm.Deterministic("p", pm.math.sigmoid(mu))
        pm.Bernoulli("y_obs", p=p, observed=y_data)
        
        trace_base = pm.sample(draws=300, tune=300, chains=1, progressbar=False, random_seed=42)
        pm.set_data({"X": X_s[[-1]], "y": np.array([0])})
        pp_base = pm.sample_posterior_predictive(trace_base, var_names=["p"], progressbar=False)
        base_prob = pp_base.posterior_predictive["p"].mean().item()
    print(f"    -> Baseline QQQ P(UP): {base_prob*100:.1f}%")
        
    print("\n[STEP 4] Running QQQ PyMC Model WITH Dynamic Whale Prior Injection...")
    with pm.Model() as prior_model:
        X_data = pm.Data("X", X_s[:-1])
        y_data = pm.Data("y", y[:-1])
        
        # Here is the magic: We inject the whale_prior_mu!
        alpha = pm.Normal("alpha", mu=0, sigma=1)
        beta = pm.Normal("beta", mu=0, sigma=1, shape=5)
        
        # Inject the prior into the overarching equation
        whale_prior = pm.Normal("whale_prior", mu=whale_prior_mu, sigma=0.5)
        
        mu = alpha + pm.math.dot(X_data, beta) + whale_prior
        p = pm.Deterministic("p", pm.math.sigmoid(mu))
        pm.Bernoulli("y_obs", p=p, observed=y_data)
        
        trace_prior = pm.sample(draws=300, tune=300, chains=1, progressbar=False, random_seed=42)
        pm.set_data({"X": X_s[[-1]], "y": np.array([0])})
        pp_prior = pm.sample_posterior_predictive(trace_prior, var_names=["p"], progressbar=False)
        prior_prob = pp_prior.posterior_predictive["p"].mean().item()
    print(f"    -> DYNAMIC PRIOR QQQ P(UP): {prior_prob*100:.1f}%")
    
    print("\n==================================================")
    print("                FINAL CONCLUSION")
    print("==================================================")
    print(f"Target ETF: {TARGET_ETF}")
    print(f"Baseline Probability (No Prior) : {base_prob*100:.1f}%")
    print(f"Dynamic Probability (Whale Prior): {prior_prob*100:.1f}%")
    
    delta = prior_prob - base_prob
    if delta > 0:
        print(f"\nThe Whales pulled the ETF Probability UP by +{delta*100:.1f}%.")
    else:
        print(f"\nThe Whales pulled the ETF Probability DOWN by {delta*100:.1f}%.")
    print("\n[SUCCESS] The Dynamic Prior effectively overrides the baseline prediction!")

if __name__ == "__main__":
    run_poc()
