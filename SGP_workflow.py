import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
import pymc as pm
import os

os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv'
champion_ticker = 'JPM'

print("Reading S&P 500 data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

# Use FULL data available (removing the 12-month limit)
min_date = df['Date'].min()
max_date = df['Date'].max()
print(f"Using FULL data: {min_date.date()} to {max_date.date()}")

print("Encoding categorical variables...")
df['RAS_Signal_Num'] = df['RAS_Signal'].map({'BUY': 1, 'HOLD': 0, 'SELL': -1}).fillna(0)
df['Market_Fear_Level_Num'] = df['Market_Fear_Level_x'].map({'Complacency / Calm': 0, 'High Volatility': 1}).fillna(0)

print("Preparing predictors...")
return_pivot = df.pivot(index='Date', columns='Ticker', values='Daily_Return_%')
stdev_pivot = df.pivot(index='Date', columns='Ticker', values='Daily_STDEV')
rsi_pivot = df.pivot(index='Date', columns='Ticker', values='RSI_14d')
adx_pivot = df.pivot(index='Date', columns='Ticker', values='ADX_14d')
plus_di_pivot = df.pivot(index='Date', columns='Ticker', values='Plus_DI_14d')
minus_di_pivot = df.pivot(index='Date', columns='Ticker', values='Minus_DI_14d')
atr_pivot = df.pivot(index='Date', columns='Ticker', values='ATR_14d')
ras_signal_pivot = df.pivot(index='Date', columns='Ticker', values='RAS_Signal_Num')

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
    })
    predictors_list.append(df_tick)

all_predictors_df = pd.concat(predictors_list, axis=1)
macro_df = df.drop_duplicates(subset=['Date']).set_index('Date')[['VIX_Close_x', 'Market_Fear_Level_Num']]
all_predictors_df = pd.concat([all_predictors_df, macro_df], axis=1)

def run_pymc_gp_experiment(target_series, predictors_df, lag, exp_name):
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
    
    # Pre-select top 7 predictors based on correlation
    corrs = X_pool_train.corrwith(pd.Series(y_train, index=X_pool_train.index))
    top_7_features = corrs.abs().sort_values(ascending=False).head(7).index.tolist()
    print(f"Top 7 predictors selected: {top_7_features}")
    
    X_train = X_pool_train[top_7_features].values
    X_test = X_pool_test[top_7_features].values
    
    # Scale X for GP stability (CRITICAL for ExpQuad kernel)
    X_mean = X_train.mean(axis=0)
    X_std = X_train.std(axis=0) + 1e-8
    X_train_scaled = (X_train - X_mean) / X_std
    X_test_scaled = (X_test - X_mean) / X_std
    
    with pm.Model() as model:
        # ARD Kernel (length scale for each feature independently)
        ls = pm.Gamma("ls", alpha=2, beta=1, shape=7)
        # Using variance/amplitude for the kernel
        eta = pm.HalfNormal("eta", sigma=np.std(y_train))
        cov_func = eta**2 * pm.gp.cov.ExpQuad(input_dim=7, ls=ls)
        
        # Sparse GP Approximation using KMeans for inducing points
        num_inducing = min(150, len(X_train_scaled))
        kmeans = KMeans(n_clusters=num_inducing, random_state=42, n_init=10).fit(X_train_scaled)
        Xu = kmeans.cluster_centers_
        
        # Marginal Approximate GP (Sparse GP)
        gp = pm.gp.MarginalApprox(cov_func=cov_func, approx="FITC")
        
        # Noise variance
        sigma = pm.HalfNormal("sigma", sigma=np.std(y_train))
        
        # Marginal likelihood with inducing points
        y_obs = gp.marginal_likelihood("y_obs", X=X_train_scaled, Xu=Xu, y=y_train, sigma=sigma)
        
        # Sample hyper-parameters ONLY (very fast)
        trace = pm.sample(draws=300, tune=300, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
        
        # Add out-of-sample prediction node AFTER sampling so NUTS ignores it
        f_pred = gp.conditional("f_pred", Xnew=X_test_scaled)
        
        # Generate predictions from the analytic posterior
        post_pred = pm.sample_posterior_predictive(trace, var_names=["f_pred"], progressbar=False)
        
    y_pred_test = post_pred.posterior_predictive["f_pred"].mean(dim=["chain", "draw"]).values
    
    y_test_mean = y_test.mean()
    ss_res = np.sum((y_test - y_pred_test) ** 2)
    ss_tot = np.sum((y_test - y_test_mean) ** 2)
    
    r2_test = 1 - (ss_res / ss_tot) if ss_tot != 0 else np.nan
    
    print(f"Finished {exp_name} (Lag {lag}) -> Out-of-Sample R2: {r2_test:.4f}")
    dates_test = data.index[split_idx:]
    res_dict = {'Experiment': exp_name, 'Lag': lag, 'Test R2': r2_test, 'Predictors': ", ".join(top_7_features)}
    return res_dict, dates_test, y_test, y_pred_test

if __name__ == '__main__':
    results = []
    
    # Best target: MA3 of Return/StdDev (volatility-adjusted)
    target_adj_ma3 = std_adj_returns[champion_ticker].rolling(window=3).mean().rename(f'{champion_ticker}_Target_AdjMA3')
    
    # Run Lag 1
    res1, dates1, y_test1, y_pred1 = run_pymc_gp_experiment(target_adj_ma3, all_predictors_df, 1, f"{champion_ticker} GP AdjMA3 (Lag 1)")
    results.append(res1)
    
    # Run Lag 2
    res2, dates2, y_test2, y_pred2 = run_pymc_gp_experiment(target_adj_ma3, all_predictors_df, 2, f"{champion_ticker} GP AdjMA3 (Lag 2)")
    results.append(res2)
    
    summary_df = pd.DataFrame(results)
    print("\n\n=== Final PyMC GP Workflow Summary ===")
    print(summary_df.to_string(index=False))
    
    # --- Build the last-30-day Scorecard Table ---
    # Raw daily return for reference (not adjusted, not smoothed)
    raw_return = return_pivot[champion_ticker].rename('Actual_Daily_Return_%')
    
    # Build Lag 1 scorecard
    lag1_df = pd.DataFrame({
        'Actual_AdjMA3':   y_test1,
        'Pred_Lag1':       y_pred1,
    }, index=dates1)
    
    # Build Lag 2 scorecard
    lag2_df = pd.DataFrame({
        'Pred_Lag2':       y_pred2,
    }, index=dates2)
    
    # Merge on date — use inner join so we only keep days both lags predicted
    scorecard = lag1_df.join(lag2_df, how='inner')
    
    # Join the actual raw daily return
    scorecard = scorecard.join(raw_return, how='left')
    
    # On Target = predicted sign matches actual sign (of the adj MA3 target)
    scorecard['Lag1_Signal']   = np.where(scorecard['Pred_Lag1'] > 0, 'BUY', 'SELL')
    scorecard['Lag2_Signal']   = np.where(scorecard['Pred_Lag2'] > 0, 'BUY', 'SELL')
    scorecard['Actual_Signal'] = np.where(scorecard['Actual_AdjMA3'] > 0, 'BUY', 'SELL')
    
    scorecard['Lag1_Result'] = np.where(scorecard['Lag1_Signal'] == scorecard['Actual_Signal'], 'On Target', 'Miss')
    scorecard['Lag2_Result'] = np.where(scorecard['Lag2_Signal'] == scorecard['Actual_Signal'], 'On Target', 'Miss')
    
    # Take last 30 days
    last30 = scorecard.tail(30).copy()
    last30.index = last30.index.strftime('%Y-%m-%d')
    
    display_cols = ['Actual_Daily_Return_%', 'Lag1_Signal', 'Lag1_Result', 'Lag2_Signal', 'Lag2_Result']
    last30_display = last30[display_cols].copy()
    last30_display['Actual_Daily_Return_%'] = last30_display['Actual_Daily_Return_%'].round(3)
    
    print("\n\n=== Last 30 Days Prediction Scorecard ===")
    print(last30_display.to_string())
    
    # Accuracy summary
    lag1_acc = (last30['Lag1_Result'] == 'On Target').mean() * 100
    lag2_acc = (last30['Lag2_Result'] == 'On Target').mean() * 100
    print(f"\nLag 1 Directional Accuracy (last 30 days): {lag1_acc:.1f}%")
    print(f"Lag 2 Directional Accuracy (last 30 days): {lag2_acc:.1f}%")
    
    # Save to CSV
    csv_path = r'C:\Users\AviShemla\AntiGravity\JPM_GP_Scorecard_Last30.csv'
    last30_display.to_csv(csv_path)
    print(f"\nScorecard saved to: {csv_path}")
    
    out_path = r'C:\Users\AviShemla\AntiGravity\PyMC_TGT_GP_Results.csv'
    summary_df.to_csv(out_path, index=False)
    
    # --- Side-by-side comparison plot ---
    fig, axes = plt.subplots(2, 1, figsize=(16, 12), sharex=False)
    fig.suptitle(f"{champion_ticker} — Raw MA3 vs Volatility-Adjusted MA3 Predictions (Lag 1, Out-of-Sample)", fontsize=14, fontweight='bold')
    
    # Top: Raw MA3
    axes[0].plot(dates1, y_test1, label='Actual', color='steelblue', alpha=0.6)
    axes[0].plot(dates1, y_pred1, label=f'Predicted  |  R²={res1["Test R2"]:.3f}', color='red', linewidth=2)
    axes[0].set_title('Target: 3-Day Moving Average of Raw Daily Return')
    axes[0].set_ylabel('Return %')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # Bottom: Adjusted MA3
    axes[1].plot(dates2, y_test2, label='Actual', color='steelblue', alpha=0.6)
    axes[1].plot(dates2, y_pred2, label=f'Predicted  |  R²={res2["Test R2"]:.3f}', color='darkorange', linewidth=2)
    axes[1].set_title('Target: 3-Day Moving Average of Return / StdDev (Volatility-Adjusted)')
    axes[1].set_ylabel('Z-Score')
    axes[1].set_xlabel('Date (Days)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    
    plt.tight_layout()
    plot_path = r'C:\Users\AviShemla\AntiGravity\JPM_GP_Comparison_Plot.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    print(f"\nComparison plot saved to: {plot_path}")
    plt.close()

