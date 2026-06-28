import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import os

os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv'
champion_ticker = 'JPM'

print("Reading S&P 500 data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

# Filter to last 12 months
max_date = df['Date'].max()
start_date = max_date - pd.DateOffset(months=12)
df = df[df['Date'] >= start_date].copy()
print(f"Data filtered to last 12 months: {start_date.date()} to {max_date.date()}")

print("Encoding categorical variables...")
df['RAS_Signal_Num'] = df['RAS_Signal'].map({'BUY': 1, 'HOLD': 0, 'SELL': -1}).fillna(0)
df['RAS_Intercept_Signal_Num'] = df['RAS_Intercept_Signal'].map({'Trend_Reversal_BUY': 1, 'HOLD': 0, 'Trend_Reversal_SELL': -1}).fillna(0)
df['Market_Fear_Level_Num'] = df['Market_Fear_Level'].map({'Complacency / Calm': 0, 'High Volatility': 1}).fillna(0)

print("Preparing predictors...")
return_pivot = df.pivot(index='Date', columns='Ticker', values='Daily_Return_%')
stdev_pivot = df.pivot(index='Date', columns='Ticker', values='Daily_STDEV')
rsi_pivot = df.pivot(index='Date', columns='Ticker', values='RSI_14d')
adx_pivot = df.pivot(index='Date', columns='Ticker', values='ADX_14d')
plus_di_pivot = df.pivot(index='Date', columns='Ticker', values='Plus_DI_14d')
minus_di_pivot = df.pivot(index='Date', columns='Ticker', values='Minus_DI_14d')
atr_pivot = df.pivot(index='Date', columns='Ticker', values='ATR_14d')
ras_signal_pivot = df.pivot(index='Date', columns='Ticker', values='RAS_Signal_Num')
ras_intercept_pivot = df.pivot(index='Date', columns='Ticker', values='RAS_Intercept_Signal_Num')

std_adj_returns = return_pivot / (stdev_pivot + 1e-8)

predictors_list = []
for ticker in std_adj_returns.columns:
    df_tick = pd.DataFrame({
        f'{ticker}_RET_ADJ': std_adj_returns[ticker],
        f'{ticker}_RSI': rsi_pivot[ticker],
        f'{ticker}_ADX': adx_pivot[ticker],
        f'{ticker}_PLUS_DI': plus_di_pivot[ticker],
        f'{ticker}_MINUS_DI': minus_di_pivot[ticker],
        f'{ticker}_ATR': atr_pivot[ticker],
        f'{ticker}_RAS': ras_signal_pivot[ticker],
        f'{ticker}_RAS_INT': ras_intercept_pivot[ticker]
    })
    predictors_list.append(df_tick)

all_predictors_df = pd.concat(predictors_list, axis=1)

macro_df = df.drop_duplicates(subset=['Date']).set_index('Date')[['VIX_Close', 'Market_Fear_Level_Num']]
all_predictors_df = pd.concat([all_predictors_df, macro_df], axis=1)

def run_pymc_experiment(target_series, predictors_df, lag, exp_name):
    print(f"\n--- Starting {exp_name} (Lag {lag}) ---")
    
    target = target_series.copy()
    shifted_predictors = predictors_df.shift(lag)
    
    data = pd.concat([target, shifted_predictors], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    
    if len(data) < 20:
        print("Not enough data to run the model after dropna().")
        return {'Experiment': exp_name, 'Lag': lag, 'Test R2': np.nan, 'Predictors': "N/A"}
        
    y_full = data.iloc[:, 0].values
    X_pool_full = data.iloc[:, 1:]
    
    split_idx = int(len(data) * 0.8)
    y_train = y_full[:split_idx]
    X_pool_train = X_pool_full.iloc[:split_idx]
    y_test = y_full[split_idx:]
    X_pool_test = X_pool_full.iloc[split_idx:]
    
    corrs = X_pool_train.corrwith(pd.Series(y_train, index=X_pool_train.index))
    top_5_features = corrs.abs().sort_values(ascending=False).head(5).index.tolist()
    print(f"Top 5 predictors selected: {top_5_features}")
    
    X_train = X_pool_train[top_5_features].values
    X_test = X_pool_test[top_5_features].values
    
    with pm.Model() as model:
        alpha = pm.Normal("alpha", mu=0, sigma=0.01)
        beta = pm.Normal("beta", mu=0, sigma=0.01, shape=len(top_5_features))
        sigma = pm.Exponential("sigma", lam=100)
        
        mu = alpha + pm.math.dot(X_train, beta)
        y_obs = pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y_train)
        
        trace = pm.sample(draws=500, tune=500, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
    
    posterior_samples = az.extract(trace)
    alpha_post = posterior_samples.alpha.mean().values
    beta_post = posterior_samples.beta.mean(axis=1).values
    
    y_pred_test = alpha_post + np.dot(X_test, beta_post)
    
    y_test_mean = y_test.mean()
    ss_res = np.sum((y_test - y_pred_test) ** 2)
    ss_tot = np.sum((y_test - y_test_mean) ** 2)
    
    r2_test = 1 - (ss_res / ss_tot) if ss_tot != 0 else np.nan
    
    print(f"Finished {exp_name} (Lag {lag}) -> Out-of-Sample R2: {r2_test:.4f}")
    return {'Experiment': exp_name, 'Lag': lag, 'Test R2': r2_test, 'Predictors': ", ".join(top_5_features)}

if __name__ == '__main__':
    results = []
    
    # NEW: Predicting the absolute magnitude of the return (Volatility)
    target_returns = np.abs(return_pivot[champion_ticker]).rename(f'{champion_ticker}_Abs_Target')
    
    for l in [1, 2, 3]:
        res = run_pymc_experiment(target_returns, all_predictors_df, l, "JPM Volatility (Abs Return)")
        results.append(res)
        
    summary_df = pd.DataFrame(results)
    print("\n\n=== Final PyMC Volatility Workflow Summary ===")
    print(summary_df.to_string(index=False))
    
    out_path = r'C:\Users\AviShemla\AntiGravity\PyMC_JPM_Volatility_Results.csv'
    summary_df.to_csv(out_path, index=False)
