# =============================================================================
# MODEL: Bayesian Neural Network (BNN)
# Naming Convention: BNN_workflow.py
# Targets: (1) MA3 of Daily Return  (2) MA3 of Daily Return / StdDev
# =============================================================================
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import pymc as pm
import os

os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'SP500_Clean_Advanced_Analysis.csv')
champion_ticker = 'JPM'

print("Reading S&P 500 data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

# Use FULL data available
min_date = df['Date'].min()
max_date = df['Date'].max()
print(f"Using FULL data: {min_date.date()} to {max_date.date()}")

print("Encoding categorical variables...")
df['RAS_Signal_Num'] = df['RAS_Signal'].map({'BUY': 1, 'HOLD': 0, 'SELL': -1}).fillna(0)
df['RAS_Intercept_Signal_Num'] = df['RAS_Intercept_Signal'].map({'Trend_Reversal_BUY': 1, 'HOLD': 0, 'Trend_Reversal_SELL': -1}).fillna(0)
df['Market_Fear_Level_Num'] = df['Market_Fear_Level'].map({'Complacency / Calm': 0, 'High Volatility': 1}).fillna(0)

print("Preparing predictors...")
return_pivot   = df.pivot(index='Date', columns='Ticker', values='Daily_Return_%')
stdev_pivot    = df.pivot(index='Date', columns='Ticker', values='Daily_STDEV')
rsi_pivot      = df.pivot(index='Date', columns='Ticker', values='RSI_14d')
adx_pivot      = df.pivot(index='Date', columns='Ticker', values='ADX_14d')
plus_di_pivot  = df.pivot(index='Date', columns='Ticker', values='Plus_DI_14d')
minus_di_pivot = df.pivot(index='Date', columns='Ticker', values='Minus_DI_14d')
atr_pivot      = df.pivot(index='Date', columns='Ticker', values='ATR_14d')
ras_signal_pivot     = df.pivot(index='Date', columns='Ticker', values='RAS_Signal_Num')
ras_intercept_pivot  = df.pivot(index='Date', columns='Ticker', values='RAS_Intercept_Signal_Num')

std_adj_returns = return_pivot / (stdev_pivot + 1e-8)

predictors_list = []
for ticker in std_adj_returns.columns:
    df_tick = pd.DataFrame({
        f'{ticker}_RET_ADJ':   std_adj_returns[ticker],
        f'{ticker}_RSI':       rsi_pivot[ticker],
        f'{ticker}_ADX':       adx_pivot[ticker],
        f'{ticker}_PLUS_DI':   plus_di_pivot[ticker],
        f'{ticker}_MINUS_DI':  minus_di_pivot[ticker],
        f'{ticker}_ATR':       atr_pivot[ticker],
        f'{ticker}_RAS':       ras_signal_pivot[ticker],
        f'{ticker}_RAS_INT':   ras_intercept_pivot[ticker]
    })
    predictors_list.append(df_tick)

all_predictors_df = pd.concat(predictors_list, axis=1)
macro_df = df.drop_duplicates(subset=['Date']).set_index('Date')[['VIX_Close', 'Market_Fear_Level_Num']]
all_predictors_df = pd.concat([all_predictors_df, macro_df], axis=1)


def run_bnn_experiment(target_series, predictors_df, lag, exp_name, n_hidden1=16, n_hidden2=8):
    print(f"\n--- Starting {exp_name} (Lag {lag}) ---")

    target = target_series.copy()
    shifted_predictors = predictors_df.shift(lag)

    data = pd.concat([target, shifted_predictors], axis=1).replace([np.inf, -np.inf], np.nan).dropna()

    if len(data) < 20:
        print("Not enough data to run the model after dropna().")
        return {'Experiment': exp_name, 'Lag': lag, 'Test R2': np.nan, 'Predictors': "N/A"}, None, None, None

    y_full      = data.iloc[:, 0].values
    X_pool_full = data.iloc[:, 1:]

    split_idx    = int(len(data) * 0.8)
    y_train      = y_full[:split_idx]
    X_pool_train = X_pool_full.iloc[:split_idx]
    y_test       = y_full[split_idx:]
    X_pool_test  = X_pool_full.iloc[split_idx:]

    # Pre-select top 7 predictors based on correlation
    corrs = X_pool_train.corrwith(pd.Series(y_train, index=X_pool_train.index))
    top_7_features = corrs.abs().sort_values(ascending=False).head(7).index.tolist()
    print(f"Top 7 predictors selected: {top_7_features}")

    X_train = X_pool_train[top_7_features].values
    X_test  = X_pool_test[top_7_features].values

    # Standardise inputs (critical for neural nets)
    X_mean = X_train.mean(axis=0)
    X_std  = X_train.std(axis=0) + 1e-8
    X_train_s = (X_train - X_mean) / X_std
    X_test_s  = (X_test  - X_mean) / X_std

    n_features = X_train_s.shape[1]
    y_std = float(np.std(y_train))

    with pm.Model() as model:
        # --- Layer 1 weights & biases ---
        W1 = pm.Normal("W1", mu=0, sigma=1, shape=(n_features, n_hidden1))
        b1 = pm.Normal("b1", mu=0, sigma=1, shape=(n_hidden1,))

        # --- Layer 2 weights & biases ---
        W2 = pm.Normal("W2", mu=0, sigma=1, shape=(n_hidden1, n_hidden2))
        b2 = pm.Normal("b2", mu=0, sigma=1, shape=(n_hidden2,))

        # --- Output layer ---
        W3 = pm.Normal("W3", mu=0, sigma=1, shape=(n_hidden2,))
        b3 = pm.Normal("b3", mu=0, sigma=1)

        # --- Forward pass (tanh activations) ---
        h1  = pm.math.tanh(pm.math.dot(X_train_s, W1) + b1)
        h2  = pm.math.tanh(pm.math.dot(h1, W2) + b2)
        mu  = pm.math.dot(h2, W3) + b3

        # --- Observation noise ---
        sigma = pm.HalfNormal("sigma", sigma=y_std)

        # --- Likelihood ---
        y_obs = pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y_train)

        # --- Sample (NUTS) ---
        trace = pm.sample(
            draws=300, tune=300, chains=2,
            target_accept=0.9, random_seed=42,
            progressbar=False
        )

    # --- Out-of-sample prediction via posterior means ---
    W1_post = trace.posterior["W1"].mean(dim=["chain", "draw"]).values
    b1_post = trace.posterior["b1"].mean(dim=["chain", "draw"]).values
    W2_post = trace.posterior["W2"].mean(dim=["chain", "draw"]).values
    b2_post = trace.posterior["b2"].mean(dim=["chain", "draw"]).values
    W3_post = trace.posterior["W3"].mean(dim=["chain", "draw"]).values
    b3_post = float(trace.posterior["b3"].mean(dim=["chain", "draw"]).values)

    h1_test     = np.tanh(X_test_s @ W1_post + b1_post)
    h2_test     = np.tanh(h1_test @ W2_post + b2_post)
    y_pred_test = h2_test @ W3_post + b3_post

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
    res1, dates1, y_test1, y_pred1 = run_bnn_experiment(
        target_adj_ma3, all_predictors_df, 1, f"{champion_ticker} BNN AdjMA3 (Lag 1)"
    )
    results.append(res1)

    # Run Lag 2
    res2, dates2, y_test2, y_pred2 = run_bnn_experiment(
        target_adj_ma3, all_predictors_df, 2, f"{champion_ticker} BNN AdjMA3 (Lag 2)"
    )
    results.append(res2)

    summary_df = pd.DataFrame(results)
    print("\n\n=== BNN Workflow Summary ===")
    print(summary_df.to_string(index=False))

    # --- Build the last-30-day Scorecard Table ---
    raw_return = return_pivot[champion_ticker].rename('Actual_Daily_Return_%')

    lag1_df = pd.DataFrame({'Actual_AdjMA3': y_test1, 'Pred_Lag1': y_pred1}, index=dates1)
    lag2_df = pd.DataFrame({'Pred_Lag2': y_pred2}, index=dates2)

    scorecard = lag1_df.join(lag2_df, how='inner').join(raw_return, how='left')

    scorecard['Lag1_Signal']   = np.where(scorecard['Pred_Lag1'] > 0, 'BUY', 'SELL')
    scorecard['Lag2_Signal']   = np.where(scorecard['Pred_Lag2'] > 0, 'BUY', 'SELL')
    scorecard['Actual_Signal'] = np.where(scorecard['Actual_AdjMA3'] > 0, 'BUY', 'SELL')
    scorecard['Lag1_Result']   = np.where(scorecard['Lag1_Signal'] == scorecard['Actual_Signal'], 'On Target', 'Miss')
    scorecard['Lag2_Result']   = np.where(scorecard['Lag2_Signal'] == scorecard['Actual_Signal'], 'On Target', 'Miss')

    last30 = scorecard.tail(30).copy()
    last30.index = last30.index.strftime('%Y-%m-%d')

    display_cols = ['Actual_Daily_Return_%', 'Lag1_Signal', 'Lag1_Result', 'Lag2_Signal', 'Lag2_Result']
    last30_display = last30[display_cols].copy()
    last30_display['Actual_Daily_Return_%'] = last30_display['Actual_Daily_Return_%'].round(3)

    print("\n\n=== Last 30 Days BNN Prediction Scorecard ===")
    print(last30_display.to_string())

    lag1_acc = (last30['Lag1_Result'] == 'On Target').mean() * 100
    lag2_acc = (last30['Lag2_Result'] == 'On Target').mean() * 100
    print(f"\nBNN Lag 1 Directional Accuracy (last 30 days): {lag1_acc:.1f}%")
    print(f"BNN Lag 2 Directional Accuracy (last 30 days): {lag2_acc:.1f}%")

    # --- Side-by-side plot: Lag 1 vs Lag 2 ---
    fig, axes = plt.subplots(2, 1, figsize=(16, 12), sharex=False)
    fig.suptitle(f"{champion_ticker} — BNN Actual vs Predicted (Vol-Adjusted MA3, Out-of-Sample)", fontsize=14, fontweight='bold')

    axes[0].plot(dates1, y_test1, label='Actual', color='steelblue', alpha=0.6)
    axes[0].plot(dates1, y_pred1, label=f'BNN Predicted  |  R²={res1["Test R2"]:.3f}', color='crimson', linewidth=2)
    axes[0].set_title('Lag 1 (predict using yesterday\'s sector data)')
    axes[0].set_ylabel('Z-Score (Return/StdDev)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(dates2, y_test2, label='Actual', color='steelblue', alpha=0.6)
    axes[1].plot(dates2, y_pred2, label=f'BNN Predicted  |  R²={res2["Test R2"]:.3f}', color='darkorange', linewidth=2)
    axes[1].set_title('Lag 2 (predict using 2-days-ago sector data)')
    axes[1].set_ylabel('Z-Score (Return/StdDev)')
    axes[1].set_xlabel('Date (Days)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'BNN_JPM_Predictions.png')
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    print(f"\nPlot saved to: {plot_path}")
    plt.close()

    # Save scorecard
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'BNN_JPM_Scorecard_Last30.csv')
    last30_display.to_csv(csv_path)
    print(f"Scorecard saved to: {csv_path}")
