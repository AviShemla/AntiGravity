# =============================================================================
# MODEL: Bayesian Hidden Markov Model (BHMM)
# Naming Convention: BHMM_workflow.py
# Approach:
#   1. Identify K hidden market regimes via Gaussian Mixture Model (E-step)
#   2. Learn Bayesian transition matrix (Dirichlet priors) + emission means
#      (Normal priors) via PyMC (M-step) -> full Bayesian HMM
#   3. Predict next-day return = E[y | predicted next regime]
#   4. Produce same scorecard as SGP for apples-to-apples comparison
# =============================================================================
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import pymc as pm
from sklearn.mixture import GaussianMixture
import os

os.environ["PYTENSOR_FLAGS"] = "cxx="

# --- Config ---
input_file    = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv'
champion_ticker = 'JPM'
N_STATES      = 3   # hidden regimes: bear / neutral / bull

print("Reading S&P 500 data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

min_date = df['Date'].min()
max_date = df['Date'].max()
print(f"Using FULL data: {min_date.date()} to {max_date.date()}")

print("Encoding categorical variables...")
df['RAS_Signal_Num'] = df['RAS_Signal'].map({'BUY': 1, 'HOLD': 0, 'SELL': -1}).fillna(0)
df['Market_Fear_Level_Num'] = df['Market_Fear_Level'].map({'Complacency / Calm': 0, 'High Volatility': 1}).fillna(0)

print("Preparing predictors...")
return_pivot   = df.pivot(index='Date', columns='Ticker', values='Daily_Return_%')
stdev_pivot    = df.pivot(index='Date', columns='Ticker', values='Daily_STDEV')
rsi_pivot      = df.pivot(index='Date', columns='Ticker', values='RSI_14d')
adx_pivot      = df.pivot(index='Date', columns='Ticker', values='ADX_14d')
plus_di_pivot  = df.pivot(index='Date', columns='Ticker', values='Plus_DI_14d')
minus_di_pivot = df.pivot(index='Date', columns='Ticker', values='Minus_DI_14d')
atr_pivot      = df.pivot(index='Date', columns='Ticker', values='ATR_14d')
ras_pivot      = df.pivot(index='Date', columns='Ticker', values='RAS_Signal_Num')

std_adj_returns = return_pivot / (stdev_pivot + 1e-8)

predictors_list = []
for ticker in std_adj_returns.columns:
    df_tick = pd.DataFrame({
        f'{ticker}_RET_ADJ':  std_adj_returns[ticker],
        f'{ticker}_RSI':      rsi_pivot[ticker],
        f'{ticker}_ADX':      adx_pivot[ticker],
        f'{ticker}_PLUS_DI':  plus_di_pivot[ticker],
        f'{ticker}_MINUS_DI': minus_di_pivot[ticker],
        f'{ticker}_ATR':      atr_pivot[ticker],
        f'{ticker}_RAS':      ras_pivot[ticker],
    })
    predictors_list.append(df_tick)

all_predictors_df = pd.concat(predictors_list, axis=1)
macro_df = df.drop_duplicates(subset=['Date']).set_index('Date')[['VIX_Close', 'Market_Fear_Level_Num']]
all_predictors_df = pd.concat([all_predictors_df, macro_df], axis=1)


def run_bhmm_experiment(target_series, predictors_df, lag, exp_name):
    print(f"\n--- Starting {exp_name} (Lag {lag}) ---")

    target = target_series.copy()
    shifted_predictors = predictors_df.shift(lag)

    data = pd.concat([target, shifted_predictors], axis=1).replace([np.inf, -np.inf], np.nan).dropna()

    if len(data) < 50:
        print("Not enough data.")
        return {'Experiment': exp_name, 'Lag': lag, 'Test R2': np.nan, 'Predictors': 'N/A'}, None, None, None

    y_full      = data.iloc[:, 0].values
    X_pool_full = data.iloc[:, 1:]

    split_idx    = int(len(data) * 0.8)
    y_train      = y_full[:split_idx]
    X_pool_train = X_pool_full.iloc[:split_idx]
    y_test       = y_full[split_idx:]
    X_pool_test  = X_pool_full.iloc[split_idx:]

    # --- Top 7 predictor selection by correlation ---
    corrs = X_pool_train.corrwith(pd.Series(y_train, index=X_pool_train.index))
    top_7 = corrs.abs().sort_values(ascending=False).head(7).index.tolist()
    print(f"Top 7 predictors: {top_7}")

    X_train = X_pool_train[top_7].values
    X_test  = X_pool_test[top_7].values

    # Standardise
    X_mean = X_train.mean(axis=0);  X_std = X_train.std(axis=0) + 1e-8
    X_train_s = (X_train - X_mean) / X_std
    X_test_s  = (X_test  - X_mean) / X_std

    # ==========================================================
    # STEP 1: Identify K hidden regimes via GMM on training data
    # ==========================================================
    gmm = GaussianMixture(n_components=N_STATES, covariance_type='full',
                          random_state=42, n_init=5, max_iter=300)
    gmm.fit(X_train_s)

    states_train = gmm.predict(X_train_s)   # hard state assignments
    states_test  = gmm.predict(X_test_s)

    print(f"Regime distribution (train): {np.bincount(states_train)}")

    # ==========================================================
    # STEP 2: Bayesian inference — learn emission means & 
    #         transition probabilities with PyMC
    # ==========================================================
    with pm.Model() as bhmm_model:

        # --- Bayesian emission means: E[y | state=k] ---
        mu_emit = pm.Normal("mu_emit", mu=0, sigma=np.std(y_train), shape=N_STATES)
        sigma_emit = pm.HalfNormal("sigma_emit", sigma=np.std(y_train), shape=N_STATES)

        # --- Likelihood: observed returns explained by their state's emission ---
        for k in range(N_STATES):
            mask = states_train == k
            if mask.sum() > 0:
                pm.Normal(f"obs_state_{k}",
                          mu=mu_emit[k], sigma=sigma_emit[k],
                          observed=y_train[mask])

        # --- Bayesian transition matrix (Dirichlet rows) ---
        trans_rows = []
        for k in range(N_STATES):
            # Count observed transitions from state k
            counts = np.zeros(N_STATES)
            for t in range(len(states_train) - 1):
                if states_train[t] == k:
                    counts[states_train[t + 1]] += 1
            alpha = counts + 1.0   # Dirichlet concentration (add-one smoothing)
            row = pm.Dirichlet(f"trans_row_{k}", a=alpha)
            trans_rows.append(row)

        # Sample
        trace = pm.sample(draws=500, tune=300, chains=2, target_accept=0.9,
                          random_seed=42, progressbar=False)

    # ==========================================================
    # STEP 3: Out-of-sample prediction using posterior means
    # ==========================================================
    mu_post    = trace.posterior["mu_emit"].mean(dim=["chain", "draw"]).values
    trans_post = np.array([
        trace.posterior[f"trans_row_{k}"].mean(dim=["chain", "draw"]).values
        for k in range(N_STATES)
    ])

    # For each test point: predict return = E[y | next_state]
    # where P(next_state | current_state) comes from transition matrix
    y_pred_test = np.array([
        float(trans_post[s] @ mu_post)   # weighted sum over possible next states
        for s in states_test
    ])

    # Sort regimes by emission mean so state 0=bear, 1=neutral, 2=bull
    regime_order = np.argsort(mu_post)
    regime_names = {regime_order[0]: "BEAR", regime_order[1]: "NEUTRAL", regime_order[2]: "BULL"}
    print(f"Learned regime emission means: { {regime_names[k]: round(mu_post[k],4) for k in range(N_STATES)} }")

    y_test_mean = y_test.mean()
    ss_res = np.sum((y_test - y_pred_test) ** 2)
    ss_tot = np.sum((y_test - y_test_mean) ** 2)
    r2_test = 1 - (ss_res / ss_tot) if ss_tot != 0 else np.nan

    print(f"Finished {exp_name} (Lag {lag}) -> Out-of-Sample R2: {r2_test:.4f}")

    dates_test = data.index[split_idx:]
    res_dict = {'Experiment': exp_name, 'Lag': lag, 'Test R2': r2_test, 'Predictors': ", ".join(top_7)}
    return res_dict, dates_test, y_test, y_pred_test


if __name__ == '__main__':
    results = []

    # Best target: MA3 of Return/StdDev (volatility-adjusted) — same as SGP winner
    target_adj_ma3 = std_adj_returns[champion_ticker].rolling(window=3).mean().rename(
        f'{champion_ticker}_Target_AdjMA3'
    )

    # Run Lag 1
    res1, dates1, y_test1, y_pred1 = run_bhmm_experiment(
        target_adj_ma3, all_predictors_df, 1, f"{champion_ticker} BHMM AdjMA3 (Lag 1)"
    )
    results.append(res1)

    # Run Lag 2
    res2, dates2, y_test2, y_pred2 = run_bhmm_experiment(
        target_adj_ma3, all_predictors_df, 2, f"{champion_ticker} BHMM AdjMA3 (Lag 2)"
    )
    results.append(res2)

    summary_df = pd.DataFrame(results)
    print("\n\n=== BHMM Workflow Summary ===")
    print(summary_df.to_string(index=False))

    # --- 30-day Scorecard ---
    raw_return = return_pivot[champion_ticker].rename('Actual_Daily_Return_%')
    lag1_df    = pd.DataFrame({'Actual_AdjMA3': y_test1, 'Pred_Lag1': y_pred1}, index=dates1)
    lag2_df    = pd.DataFrame({'Pred_Lag2': y_pred2}, index=dates2)

    scorecard  = lag1_df.join(lag2_df, how='inner').join(raw_return, how='left')
    scorecard['Lag1_Signal']   = np.where(scorecard['Pred_Lag1']    > 0, 'BUY', 'SELL')
    scorecard['Lag2_Signal']   = np.where(scorecard['Pred_Lag2']    > 0, 'BUY', 'SELL')
    scorecard['Actual_Signal'] = np.where(scorecard['Actual_AdjMA3']> 0, 'BUY', 'SELL')
    scorecard['Lag1_Result']   = np.where(scorecard['Lag1_Signal']  == scorecard['Actual_Signal'], 'On Target', 'Miss')
    scorecard['Lag2_Result']   = np.where(scorecard['Lag2_Signal']  == scorecard['Actual_Signal'], 'On Target', 'Miss')

    last30 = scorecard.tail(30).copy()
    last30.index = last30.index.strftime('%Y-%m-%d')

    display_cols    = ['Actual_Daily_Return_%', 'Lag1_Signal', 'Lag1_Result', 'Lag2_Signal', 'Lag2_Result']
    last30_display  = last30[display_cols].copy()
    last30_display['Actual_Daily_Return_%'] = last30_display['Actual_Daily_Return_%'].round(3)

    print("\n\n=== Last 30 Days BHMM Prediction Scorecard ===")
    print(last30_display.to_string())

    lag1_acc = (last30['Lag1_Result'] == 'On Target').mean() * 100
    lag2_acc = (last30['Lag2_Result'] == 'On Target').mean() * 100
    print(f"\nBHMM Lag 1 Directional Accuracy (last 30 days): {lag1_acc:.1f}%")
    print(f"BHMM Lag 2 Directional Accuracy (last 30 days): {lag2_acc:.1f}%")

    # --- Plot ---
    fig, axes = plt.subplots(2, 1, figsize=(16, 12), sharex=False)
    fig.suptitle(f"{champion_ticker} — BHMM Actual vs Predicted (Vol-Adj MA3, Out-of-Sample)",
                 fontsize=14, fontweight='bold')

    axes[0].plot(dates1, y_test1, label='Actual', color='steelblue', alpha=0.6)
    axes[0].plot(dates1, y_pred1, label=f'BHMM Lag 1  |  R²={res1["Test R2"]:.3f}', color='seagreen', linewidth=2)
    axes[0].set_title('Lag 1'); axes[0].set_ylabel('Z-Score'); axes[0].legend(); axes[0].grid(alpha=0.3)

    axes[1].plot(dates2, y_test2, label='Actual', color='steelblue', alpha=0.6)
    axes[1].plot(dates2, y_pred2, label=f'BHMM Lag 2  |  R²={res2["Test R2"]:.3f}', color='darkorange', linewidth=2)
    axes[1].set_title('Lag 2'); axes[1].set_ylabel('Z-Score'); axes[1].set_xlabel('Date')
    axes[1].legend(); axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plot_path = r'C:\Users\AviShemla\AntiGravity\financial_data\BHMM_JPM_Predictions.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    print(f"\nPlot saved to: {plot_path}")
    plt.close()

    csv_path = r'C:\Users\AviShemla\AntiGravity\financial_data\BHMM_JPM_Scorecard_Last30.csv'
    last30_display.to_csv(csv_path)
    print(f"Scorecard saved to: {csv_path}")
