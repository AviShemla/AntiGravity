import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import os
import yfinance as yf

os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv'
champion_ticker = 'WMT'

print("Reading S&P 500 data...")
df_sp500 = pd.read_csv(input_file)
df_sp500['Date'] = pd.to_datetime(df_sp500['Date'])
df_sp500 = df_sp500.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

# Filter to last 12 months for SP500
max_date = df_sp500['Date'].max()
start_date = max_date - pd.DateOffset(months=12)
df_sp500 = df_sp500[df_sp500['Date'] >= start_date].copy()
print(f"Data filtered to last 12 months: {start_date.date()} to {max_date.date()}")

# Pivot SP500 pre-calculated columns
return_pivot = df_sp500.pivot(index='Date', columns='Ticker', values='Daily_Return_%')
stdev_pivot = df_sp500.pivot(index='Date', columns='Ticker', values='Daily_STDEV')
rsi_pivot = df_sp500.pivot(index='Date', columns='Ticker', values='RSI_14d')
adx_pivot = df_sp500.pivot(index='Date', columns='Ticker', values='ADX_14d')

std_adj_returns = return_pivot / (stdev_pivot + 1e-8)

predictors_list = []
for ticker in std_adj_returns.columns:
    df_tick = pd.DataFrame({
        f'{ticker}_RET_ADJ': std_adj_returns[ticker],
        f'{ticker}_RSI': rsi_pivot[ticker],
        f'{ticker}_ADX': adx_pivot[ticker]
    })
    predictors_list.append(df_tick)

print("Downloading WMT data since it is not in the S&P 500 dataset...")
# Download slightly earlier to ensure rolling windows compute properly
wmt_data = yf.download('WMT', start=start_date - pd.Timedelta(days=40), end=max_date + pd.Timedelta(days=1))
if isinstance(wmt_data.columns, pd.MultiIndex):
    wmt_data.columns = wmt_data.columns.droplevel(1)
wmt_df = wmt_data[['Open', 'High', 'Low', 'Close', 'Volume']].reset_index()
wmt_df.rename(columns={'Date': 'Date', 'index': 'Date'}, inplace=True, errors='ignore')
wmt_df['Date'] = pd.to_datetime(wmt_df['Date']).dt.tz_localize(None)

wmt_df = wmt_df.set_index('Date').sort_index()

# Calculate WMT Indicators
wmt_returns = wmt_df['Close'].pct_change() * 100  # Match SP500 percentage scale
wmt_stdev = wmt_returns.rolling(window=5).std()
wmt_std_adj = wmt_returns / (wmt_stdev + 1e-8)

delta = wmt_df['Close'].diff()
gain = (delta.where(delta > 0, 0)).fillna(0)
loss = (-delta.where(delta < 0, 0)).fillna(0)
avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
rs = avg_gain / avg_loss
wmt_rsi = 100 - (100 / (1 + rs))

high = wmt_df['High']
low = wmt_df['Low']
close = wmt_df['Close']
up_move = high.diff()
down_move = low.diff() * -1
plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
tr1 = high - low
tr2 = (high - close.shift()).abs()
tr3 = (low - close.shift()).abs()
tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
plus_dm_smooth = pd.Series(plus_dm, index=high.index).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
minus_dm_smooth = pd.Series(minus_dm, index=high.index).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
plus_di = 100 * (plus_dm_smooth / atr)
minus_di = 100 * (minus_dm_smooth / atr)
dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
wmt_adx = dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

wmt_predictors = pd.DataFrame({
    'WMT_RET_ADJ': wmt_std_adj,
    'WMT_RSI': wmt_rsi,
    'WMT_ADX': wmt_adx
})

# Filter WMT data to match exactly the SP500 date range
wmt_predictors = wmt_predictors[(wmt_predictors.index >= start_date) & (wmt_predictors.index <= max_date)]
wmt_returns = wmt_returns[(wmt_returns.index >= start_date) & (wmt_returns.index <= max_date)]

predictors_list.append(wmt_predictors)
all_predictors_df = pd.concat(predictors_list, axis=1)

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
    
    target_returns = wmt_returns.rename(f'{champion_ticker}_Target')
    
    for l in [1, 2, 3]:
        res = run_pymc_experiment(target_returns, all_predictors_df, l, "WMT on SP500 Tech & Vol-Adj")
        results.append(res)
        
    summary_df = pd.DataFrame(results)
    print("\n\n=== Final PyMC Technical Workflow Summary ===")
    print(summary_df.to_string(index=False))
    
    out_path = r'C:\Users\AviShemla\AntiGravity\PyMC_WMT_SP500_Technical_Results.csv'
    summary_df.to_csv(out_path, index=False)
