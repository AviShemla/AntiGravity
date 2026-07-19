import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import matplotlib.pyplot as plt
import os

input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Nasdaq_Data_All_Sectors_Combined.csv')
champion_ticker = 'GOOG'
predictor_tickers = ['UPST', 'NVCR', 'COIN', 'U', 'SIRI']

if __name__ == '__main__':
    print("1. Data Preprocessing...")
    df = pd.read_csv(input_file)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
    pivot_df = df.pivot(index='Date', columns='Ticker', values='Close')
    returns_df = pivot_df.pct_change()

    target = returns_df[champion_ticker].iloc[1:]
    predictors = returns_df[predictor_tickers].shift(1).iloc[1:]
    data = pd.concat([target, predictors], axis=1).dropna()

    y = data[champion_ticker].values
    X = data[predictor_tickers].values

    # Split for out-of-sample check at the end
    split_idx = int(len(y) * 0.8)
    y_train, y_test = y[:split_idx], y[split_idx:]
    X_train, X_test = X[:split_idx], X[split_idx:]

    print("2. Model Specification (The Lego Approach)...")
    with pm.Model() as stock_model:
        # Priors for unknown model parameters
        alpha = pm.Normal("alpha", mu=0, sigma=0.01)
        beta = pm.Normal("beta", mu=0, sigma=0.01, shape=len(predictor_tickers))
        sigma = pm.Exponential("sigma", lam=100)
        
        # Expected value of outcome
        mu = alpha + pm.math.dot(X_train, beta)
        
        # Likelihood (sampling distribution) of observations
        y_obs = pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y_train)
        
        # 3. Prior Predictive Check
        print("  Running Prior Predictive Check...")
        prior_predictive = pm.sample_prior_predictive(samples=500)
        
        # 4. Inference (Sampling)
        print("  Sampling from Posterior (Inference)...")
        # cores=1 on Windows often avoids multiprocessing issues if they persist
        trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, random_seed=42)
        
        # 5. Posterior Predictive Check
        print("  Running Posterior Predictive Check...")
        posterior_predictive = pm.sample_posterior_predictive(trace)

    print("6. Model Checking & Diagnostics...")
    # Check convergence
    summary = az.summary(trace, round_to=4)
    print("\nModel Summary & Diagnostics:")
    print(summary)

    # Plotting Results
    az.plot_trace(trace)
    plt.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pymc_trace_plots.png'))

    plt.figure()
    az.plot_ppc(posterior_predictive, num_pp_samples=100)
    plt.title("Posterior Predictive Check")
    plt.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pymc_ppc_plot.png'))

    # 7. Out-of-sample Prediction
    print("7. Out-of-sample Prediction...")
    posterior_samples = az.extract(trace)
    alpha_post = posterior_samples.alpha.mean().values
    beta_post = posterior_samples.beta.mean(axis=1).values

    y_pred_test = alpha_post + np.dot(X_test, beta_post)

    # Calculate Test R-squared
    y_test_mean = y_test.mean()
    ss_res = np.sum((y_test - y_pred_test) ** 2)
    ss_tot = np.sum((y_test - y_test_mean) ** 2)
    r2_test = 1 - (ss_res / ss_tot)

    print(f"\nFinal Out-of-Sample R-squared (PyMC Workflow): {r2_test:.4f}")
