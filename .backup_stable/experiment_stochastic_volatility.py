import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import matplotlib.pyplot as plt
import os
import time
import sys

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'financial_data', 'SP500_Clean_Advanced_Analysis.csv')
ARTIFACT_DIR = r'C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c'

def main():
    print("1. Loading Data...")
    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Isolate MU and get last 500 days
    goog_df = df[df['Ticker'] == 'MU'].sort_values('Date').tail(500).copy()
    goog_df = goog_df.dropna(subset=['Daily_Return_%'])
    
    returns = goog_df['Daily_Return_%'].values / 100.0  # Convert to pure decimals
    dates = goog_df['Date'].values
    
    # Mean-center the returns
    returns = returns - np.mean(returns)
    print(f"Data loaded: {len(returns)} days of GOOG returns.")

    print("2. Building Stochastic Volatility Model...")
    with pm.Model() as sv_model:
        # Step size of the random walk (how fast volatility changes)
        sigma = pm.Exponential('sigma', 50.0)
        
        # Degrees of freedom for Student-T distribution (handles fat tails/crashes)
        nu = pm.Exponential('nu', 0.1)
        
        # Latent Volatility Process (Gaussian Random Walk)
        # Represents the log of the volatility
        log_vol = pm.GaussianRandomWalk('log_vol', sigma=sigma, shape=len(returns))
        
        # True Volatility
        volatility = pm.math.exp(log_vol)
        
        # Observed Returns
        # We use a Student-T distribution because financial returns have fatter tails than a Normal distribution
        returns_obs = pm.StudentT(
            'returns_obs', 
            nu=nu, 
            mu=0, 
            lam=1.0 / (volatility**2), 
            observed=returns
        )

    print("3. Sampling from the Posterior...")
    start_time = time.time()
    
    trace = None
    try:
        # Try nutpie for massive speedup on Windows
        import nutpie
        print("nutpie is installed! Compiling model in Rust for hyper-fast sampling...")
        compiled_model = nutpie.compile_pymc_model(sv_model)
        trace = nutpie.sample(compiled_model, draws=1000, tune=1000, chains=2)
    except Exception as e:
        print(f"nutpie not available or failed ({e}). Falling back to standard PyMC NUTS (this may take a few minutes)...")
        with sv_model:
            # We use cores=1 on Windows to prevent multiprocessing freeze
            trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, cores=1, random_seed=42)
            
    elapsed = time.time() - start_time
    print(f"Sampling complete in {elapsed:.1f} seconds!")

    print("4. Extracting Results and Plotting...")
    posterior = az.extract(trace)
    
    # Get the mean of the latent true volatility across all draws for each day
    inferred_log_vol = posterior.log_vol.mean(axis=1).values
    inferred_volatility = np.exp(inferred_log_vol)
    
    # Get absolute actual returns for comparison
    abs_returns = np.abs(returns)
    
    plt.style.use('dark_background')
    fig, ax1 = plt.subplots(figsize=(12, 6))

    color = 'tab:blue'
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Absolute Daily Return', color=color)
    ax1.bar(dates, abs_returns, color=color, alpha=0.5, label='Actual Absolute Returns')
    ax1.tick_params(axis='y', labelcolor=color)

    ax2 = ax1.twinx()  
    color = 'tab:orange'
    ax2.set_ylabel('AI Inferred True Volatility (Latent State)', color=color)  
    ax2.plot(dates, inferred_volatility, color=color, linewidth=2, label='Inferred SV Model')
    ax2.tick_params(axis='y', labelcolor=color)
    
    # 94% HDI limits for volatility
    hdi_log_vol = az.hdi(trace, var_names=['log_vol']).log_vol.values
    hdi_lower = np.exp(hdi_log_vol[:, 0])
    hdi_upper = np.exp(hdi_log_vol[:, 1])
    ax2.fill_between(dates, hdi_lower, hdi_upper, color='tab:orange', alpha=0.2)

    plt.title('True Stochastic Volatility (Latent State) vs Actual Returns for MU')
    fig.tight_layout()  
    
    plot_path = os.path.join(ARTIFACT_DIR, 'sv_results_MU.png')
    plt.savefig(plot_path)
    print(f"Plot successfully saved to: {plot_path}")
    
    # Calculate a simple correlation to see if the latent state tracks the absolute returns
    corr = np.corrcoef(abs_returns, inferred_volatility)[0, 1]
    print(f"Correlation between Inferred Volatility and Absolute Returns: {corr:.3f}")
    
    # Analyze the last 2 days
    print("\n--- Last 2 Days Analysis ---")
    static_vol = np.std(returns[-30:]) * np.sqrt(252) # Approximate annualized 30-day vol
    print(f"Static 30-Day Rolling Volatility (approx): {static_vol:.4f}")
    
    last_2_dates = dates[-2:]
    last_2_sv = inferred_volatility[-2:]
    for i in range(2):
        print(f"{last_2_dates[i]}: Inferred SV Volatility = {last_2_sv[i]:.4f}")

if __name__ == "__main__":
    main()
