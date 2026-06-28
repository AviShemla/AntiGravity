# =============================================================================
# SGP WALK-FORWARD VALIDATION AUDIT
# Purpose: Verify the SGP R² using strict Walk-Forward TimeSeriesSplit
#          to rule out kernel over-optimization on a single lucky test window.
#
# Method: sklearn TimeSeriesSplit — training window always ends BEFORE the
#         test window starts. No future data ever touches training.
# =============================================================================
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.model_selection import TimeSeriesSplit
import pymc as pm
import os

os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file    = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv'
champion_ticker = 'JPM'
N_SPLITS      = 5   # 5 walk-forward folds

print("Reading S&P 500 data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
print(f"Full data: {df['Date'].min().date()} to {df['Date'].max().date()}")

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


def run_sgp_on_split(X_train_s, y_train, X_test_s, y_test, top_7_features):
    """Run one SGP fold and return R² + predictions."""
    with pm.Model() as model:
        ls       = pm.Gamma("ls", alpha=2, beta=1, shape=7)
        eta      = pm.HalfNormal("eta", sigma=float(np.std(y_train)))
        cov_func = eta**2 * pm.gp.cov.ExpQuad(input_dim=7, ls=ls)

        # Inducing points fit on training data ONLY
        num_inducing = min(100, len(X_train_s))
        kmeans = KMeans(n_clusters=num_inducing, random_state=42, n_init=5).fit(X_train_s)
        Xu = kmeans.cluster_centers_

        gp    = pm.gp.MarginalApprox(cov_func=cov_func, approx="FITC")
        sigma = pm.HalfNormal("sigma", sigma=float(np.std(y_train)))
        _     = gp.marginal_likelihood("y_obs", X=X_train_s, Xu=Xu, y=y_train, sigma=sigma)

        trace = pm.sample(draws=200, tune=200, chains=2,
                          target_accept=0.9, random_seed=42, progressbar=False)

        f_pred = gp.conditional("f_pred", Xnew=X_test_s)
        post_pred = pm.sample_posterior_predictive(trace, var_names=["f_pred"], progressbar=False)

    y_pred = post_pred.posterior_predictive["f_pred"].mean(dim=["chain", "draw"]).values
    ss_res = np.sum((y_test - y_pred) ** 2)
    ss_tot = np.sum((y_test - y_test.mean()) ** 2)
    r2     = 1 - ss_res / ss_tot if ss_tot != 0 else np.nan
    return r2, y_pred


if __name__ == '__main__':
    lag = 1
    print(f"\n=== Walk-Forward SGP Audit (Lag {lag}, {N_SPLITS} folds) ===\n")

    # Build the aligned dataset (same as SGP_workflow)
    target = std_adj_returns[champion_ticker].rolling(window=3).mean()
    shifted_preds = all_predictors_df.shift(lag)
    data = pd.concat([target, shifted_preds], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    data.columns = ['target'] + list(shifted_preds.columns)

    y_all     = data['target'].values
    X_pool    = data.drop(columns=['target'])
    dates_all = data.index

    tscv = TimeSeriesSplit(n_splits=N_SPLITS)

    fold_results = []

    for fold_num, (train_idx, test_idx) in enumerate(tscv.split(y_all), 1):
        print(f"--- Fold {fold_num}/{N_SPLITS} | "
              f"Train: {dates_all[train_idx[0]].date()} to {dates_all[train_idx[-1]].date()} | "
              f"Test:  {dates_all[test_idx[0]].date()} to {dates_all[test_idx[-1]].date()} "
              f"({len(test_idx)} days) ---")

        if len(train_idx) < 50 or len(test_idx) < 10:
            print("  Skipping — insufficient data in fold.")
            continue

        y_train = y_all[train_idx]
        y_test  = y_all[test_idx]
        X_train_pool = X_pool.iloc[train_idx]
        X_test_pool  = X_pool.iloc[test_idx]

        # Feature selection on training data ONLY
        corrs = X_train_pool.corrwith(pd.Series(y_train, index=X_train_pool.index))
        top_7 = corrs.abs().sort_values(ascending=False).head(7).index.tolist()

        X_train = X_train_pool[top_7].values
        X_test  = X_test_pool[top_7].values

        # Standardise using training statistics ONLY
        X_mean = X_train.mean(axis=0);  X_std = X_train.std(axis=0) + 1e-8
        X_train_s = (X_train - X_mean) / X_std
        X_test_s  = (X_test  - X_mean) / X_std

        r2, y_pred = run_sgp_on_split(X_train_s, y_train, X_test_s, y_test, top_7)

        # Directional accuracy
        dir_acc = np.mean(np.sign(y_pred) == np.sign(y_test)) * 100

        print(f"  Top 7: {top_7}")
        print(f"  R²={r2:.4f}   Directional Accuracy={dir_acc:.1f}%\n")

        fold_results.append({
            'Fold':      fold_num,
            'Train_Start': dates_all[train_idx[0]].date(),
            'Train_End':   dates_all[train_idx[-1]].date(),
            'Test_Start':  dates_all[test_idx[0]].date(),
            'Test_End':    dates_all[test_idx[-1]].date(),
            'N_Test':      len(test_idx),
            'R2':          round(r2, 4),
            'Dir_Acc_%':   round(dir_acc, 1),
            'Top7':        ", ".join(top_7)
        })

    results_df = pd.DataFrame(fold_results)
    print("\n\n=== Walk-Forward Audit Summary ===")
    print(results_df[['Fold', 'Test_Start', 'Test_End', 'N_Test', 'R2', 'Dir_Acc_%']].to_string(index=False))

    mean_r2  = results_df['R2'].mean()
    std_r2   = results_df['R2'].std()
    mean_acc = results_df['Dir_Acc_%'].mean()

    print(f"\nMean R²:              {mean_r2:.4f}  ±{std_r2:.4f}")
    print(f"Mean Dir. Accuracy:   {mean_acc:.1f}%")
    print(f"Folds with R² > 0:    {(results_df['R2'] > 0).sum()} / {len(results_df)}")

    if mean_r2 > 0.05:
        verdict = "✅ SIGNAL CONFIRMED — R² consistently positive across time periods."
    elif mean_r2 > 0:
        verdict = "⚠️  WEAK SIGNAL — positive but marginal. Could be noise."
    else:
        verdict = "❌ SIGNAL REJECTED — original R² was likely due to a lucky test window."
    print(f"\nVERDICT: {verdict}")

    # Save
    csv_path = r'C:\Users\AviShemla\AntiGravity\financial_data\SGP_WalkForward_Audit.csv'
    results_df.to_csv(csv_path, index=False)
    print(f"\nFull results saved to: {csv_path}")

    # Plot R² per fold
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ['green' if r > 0 else 'red' for r in results_df['R2']]
    ax.bar(results_df['Fold'], results_df['R2'], color=colors, alpha=0.7, edgecolor='black')
    ax.axhline(0, color='black', linewidth=1)
    ax.axhline(mean_r2, color='blue', linewidth=2, linestyle='--', label=f'Mean R²={mean_r2:.3f}')
    ax.set_xlabel('Walk-Forward Fold')
    ax.set_ylabel('Out-of-Sample R²')
    ax.set_title(f'{champion_ticker} SGP — Walk-Forward R² Across {N_SPLITS} Time Folds (Lag {lag})')
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plot_path = r'C:\Users\AviShemla\AntiGravity\financial_data\SGP_WalkForward_R2_Plot.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {plot_path}")
    plt.close()
