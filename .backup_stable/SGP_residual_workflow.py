# =============================================================================
# MODEL: SGP on AR Residual Target (SGP_residual_workflow.py)
# Target:  residual(t) = MA3_adj(t) - ar_coef * MA3_adj(t-1)
# New feature: lagged_residual(t-1) captures "how surprising was yesterday?"
# Uses shared data_loader.py for schema-resilient data loading.
# =============================================================================
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
import pymc as pm
import matplotlib.pyplot as plt
import os
import sys
sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors, prepare_sgp_data

os.environ["PYTENSOR_FLAGS"] = "cxx="

champion_ticker = 'JPM'

# ---- Load data ----
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

raw_return = return_pivot[champion_ticker]
ma3_adj    = std_adj_returns[champion_ticker].rolling(3).mean()

# ---- Compute AR(1) coefficient empirically ----
ar_align = pd.concat([ma3_adj.rename('ma3'), ma3_adj.shift(1).rename('ma3_lag1')], axis=1).dropna()
ar_coef  = LinearRegression().fit(ar_align[['ma3_lag1']], ar_align['ma3']).coef_[0]
print(f"\nEmpirical AR(1) coefficient: {ar_coef:.4f}  (theoretical: 0.6667)")

# ---- Residual target: genuinely new information each day ----
residual_target  = (ma3_adj - ar_coef * ma3_adj.shift(1)).rename('MA3_residual')
lagged_residual  = residual_target.shift(1).rename('Lagged_MA3_residual')

# Add lagged residual as an extra predictor feature
enriched_predictors = pd.concat([all_predictors_df, lagged_residual], axis=1).ffill().bfill()

print(f"Residual target: mean={residual_target.mean():.4f}, std={residual_target.std():.4f}")


def run_sgp_residual(target_series, predictors_df, lag, exp_name):
    print(f"\n--- {exp_name} (Lag {lag}) ---")
    y_train, Xt_s, y_test, Xe_s, dates_test, top7, Xm, Xs = prepare_sgp_data(
        target_series, predictors_df, lag=lag, top_k=7)

    print(f"Top 7: {top7}")
    print(f"Train: {len(y_train)} rows | Test: {len(y_test)} rows")

    with pm.Model():
        ls  = pm.Gamma("ls", alpha=2, beta=1, shape=7)
        eta = pm.HalfNormal("eta", sigma=float(np.std(y_train)))
        cov = eta**2 * pm.gp.cov.ExpQuad(input_dim=7, ls=ls)
        Xu  = KMeans(n_clusters=min(150, len(Xt_s)), random_state=42, n_init=5).fit(Xt_s).cluster_centers_
        gp  = pm.gp.MarginalApprox(cov_func=cov, approx="FITC")
        sig = pm.HalfNormal("sigma", sigma=float(np.std(y_train)))
        _   = gp.marginal_likelihood("y_obs", X=Xt_s, Xu=Xu, y=y_train, sigma=sig)
        tr  = pm.sample(draws=300, tune=300, chains=2, target_accept=0.9,
                        random_seed=42, progressbar=False)
        fp  = gp.conditional("f_pred", Xnew=Xe_s)
        pp  = pm.sample_posterior_predictive(tr, var_names=["f_pred"], progressbar=False)

    y_pred = pp.posterior_predictive["f_pred"].mean(dim=["chain", "draw"]).values

    ss_res = np.sum((y_test - y_pred)**2)
    ss_tot = np.sum((y_test - y_test.mean())**2)
    r2     = 1 - ss_res / ss_tot if ss_tot != 0 else np.nan

    raw_actual  = raw_return.reindex(dates_test).values
    dir_acc_raw = np.mean(np.sign(y_pred) == np.sign(raw_actual)) * 100

    print(f"R² on residual target:            {r2:.4f}  ({r2*100:.1f}%)")
    print(f"Directional accuracy (raw return): {dir_acc_raw:.1f}%")

    return {'Experiment': exp_name, 'Lag': lag,
            'R2_residual_target': round(r2, 4),
            'Dir_Acc_raw': round(dir_acc_raw, 1),
            'Top7': ", ".join(top7)}, dates_test, y_test, y_pred


if __name__ == '__main__':
    results = []
    res1, d1, yt1, yp1 = run_sgp_residual(residual_target, enriched_predictors, 1,
                                            f"{champion_ticker} SGP-Residual (Lag 1)")
    results.append(res1)
    res2, d2, yt2, yp2 = run_sgp_residual(residual_target, enriched_predictors, 2,
                                            f"{champion_ticker} SGP-Residual (Lag 2)")
    results.append(res2)

    print("\n\n=== SGP Residual Workflow Summary ===")
    summary = pd.DataFrame(results)
    print(summary.to_string(index=False))

    # Interpretation
    r2_1 = res1['R2_residual_target']
    print(f"\n=== GENUINE ALPHA TEST ===")
    if r2_1 > 0.05:
        print(f"R²={r2_1:.1%} on AR residual → GENUINE ALPHA confirmed beyond autocorrelation")
    elif r2_1 > 0:
        print(f"R²={r2_1:.1%} on AR residual → Weak genuine alpha, mostly autocorrelation-driven")
    else:
        print(f"R²={r2_1:.1%} on AR residual → No genuine alpha. Original R² was pure autocorrelation.")

    # Plot
    fig, axes = plt.subplots(2, 1, figsize=(16, 10))
    fig.suptitle(f"{champion_ticker} — SGP on AR Residual Target (Genuine Alpha Test)", fontsize=14, fontweight='bold')
    for ax, d, yt, yp, res in zip(axes, [d1, d2], [yt1, yt2], [yp1, yp2], results):
        ax.plot(d, yt, label='Actual Residual', color='steelblue', alpha=0.6)
        ax.plot(d, yp, label=f'Predicted  R²={res["R2_residual_target"]:.3f}', color='darkorange', linewidth=2)
        ax.axhline(0, color='black', linewidth=0.8, linestyle='--')
        ax.set_title(f'Lag {res["Lag"]} — Raw Dir Acc: {res["Dir_Acc_raw"]}%')
        ax.set_ylabel('AR Residual (z-score)')
        ax.legend(); ax.grid(alpha=0.3)

    plt.tight_layout()
    plot_path = r'C:\Users\AviShemla\AntiGravity\financial_data\SGP_Residual_Plot.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved: {plot_path}")

    summary.to_csv(r'C:\Users\AviShemla\AntiGravity\financial_data\SGP_Residual_Summary.csv', index=False)
