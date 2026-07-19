import pandas as pd
import numpy as np
import pymc as pm
import arviz as az
import os

os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Nasdaq_Data_All_Sectors_Combined.csv')
champion_ticker = 'TSCO'

import yfinance as yf

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

print("Downloading TSCO data since it is not in the NASDAQ dataset...")
min_date = df['Date'].min()
max_date = df['Date'].max()
tsco_data = yf.download('TSCO', start=min_date, end=max_date + pd.Timedelta(days=1))
# yfinance might return multi-level columns if it's a newer version, or single level.
if isinstance(tsco_data.columns, pd.MultiIndex):
    tsco_data.columns = tsco_data.columns.droplevel(1)
tsco_df = tsco_data[['Open', 'High', 'Low', 'Close', 'Volume']].reset_index()
tsco_df.rename(columns={'Date': 'Date', 'index': 'Date'}, inplace=True, errors='ignore')
tsco_df['Date'] = pd.to_datetime(tsco_df['Date']).dt.tz_localize(None)
tsco_df['Ticker'] = 'TSCO'
df = pd.concat([df, tsco_df], ignore_index=True)
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

# Filter to last 12 months
max_date = df['Date'].max()
start_date = max_date - pd.DateOffset(months=12)
df = df[df['Date'] >= start_date].copy()
print(f"Data filtered to last 12 months: {start_date.date()} to {max_date.date()}")

print("Calculating technical indicators...")
# Calculate STDEV_5d, RSI, ADX manually
df['RSI_14'] = np.nan
df['ADX_14'] = np.nan

for ticker, group in df.groupby('Ticker'):
    group = group.sort_values('Date')
    
    # RSI
    delta = group['Close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    df.loc[group.index, 'RSI_14'] = rsi
    
    # ADX
    high = group['High']
    low = group['Low']
    close = group['Close']
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
    adx = dx.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    
    df.loc[group.index, 'ADX_14'] = adx

# Pivot for Close
close_pivot = df.pivot(index='Date', columns='Ticker', values='Close')
returns_df = close_pivot.pct_change()

# Calculate STDEV_5d
stddev_5d_pivot = returns_df.rolling(window=5).std()

# Volatility-Adjusted Returns (Return / STDEV_5d)
std_adj_returns = returns_df / stddev_5d_pivot

# We also need RSI and ADX in pivot format for all tickers
rsi_pivot = df.pivot(index='Date', columns='Ticker', values='RSI_14')
adx_pivot = df.pivot(index='Date', columns='Ticker', values='ADX_14')

# We can combine these predictors or run them individually. 
# Let's combine them into one large pool of predictors:
# For example: AAPL_RET_ADJ, AAPL_RSI, AAPL_ADX
predictors_list = []
for ticker in std_adj_returns.columns:
    df_tick = pd.DataFrame({
        f'{ticker}_RET_ADJ': std_adj_returns[ticker],
        f'{ticker}_RSI': rsi_pivot[ticker],
        f'{ticker}_ADX': adx_pivot[ticker]
    })
    predictors_list.append(df_tick)

all_predictors_df = pd.concat(predictors_list, axis=1)

def run_pymc_experiment(target_series, predictors_df, lag, exp_name):
    print(f"\n--- Starting {exp_name} (Lag {lag}) ---")
    
    # Target is just WMT's raw return. Wait, the prompt says "instead of multiplying by STD, divid by SDDEV_5".
    # This might apply to the predictor returns. Should the target also be volatility adjusted?
    # Usually we predict the raw return. Let's stick to predicting raw return of WMT.
    target = target_series.copy()
    
    # Remove WMT predictors from the pool to avoid leakage if desired, 
    # but since it's lagged, predicting WMT from WMT's past is fine.
    
    # Shift predictors
    shifted_predictors = predictors_df.shift(lag)
    
    # Align
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
    
    # Target is TSCO raw returns
    target_returns = returns_df[champion_ticker].rename(f'{champion_ticker}_Target')
    
    for l in [1, 2, 3]:
        res = run_pymc_experiment(target_returns, all_predictors_df, l, "Technical & Vol-Adj")
        results.append(res)
        
    summary_df = pd.DataFrame(results)
    print("\n\n=== Final PyMC Technical Workflow Summary ===")
    print(summary_df.to_string(index=False))
    
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PyMC_TSCO_NASDAQ_Technical_Results.csv')
    summary_df.to_csv(out_path, index=False)
