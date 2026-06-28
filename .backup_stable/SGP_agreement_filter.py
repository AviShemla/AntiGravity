# =============================================================================
# SGP AGREEMENT FILTER (SGP_agreement_filter.py)
# Runs SGP for Lag1 and Lag2, applies agreement filter:
#   Agreement day = both lags predict the same direction
# Reports accuracy on all days vs agreement days vs disagreement days.
# Uses shared data_loader.py for schema-resilient data loading.
# =============================================================================
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
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
ma3_target = std_adj_returns[champion_ticker].rolling(3).mean()


def run_sgp(target_series, predictors_df, lag):
    """Run SGP for one lag. Returns (dates_test, y_pred, top7)."""
    y_train, Xt_s, y_test, Xe_s, dates_test, top7, _, _ = prepare_sgp_data(
        target_series, predictors_df, lag=lag, top_k=7)

    print(f"  Lag {lag} top 7: {top7}")
    print(f"  Train: {len(y_train)} | Test: {len(y_test)}")

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
    return dates_test, y_pred, top7


if __name__ == '__main__':
    print("\nRunning SGP Lag 1...")
    dates1, ypred1, top7_1 = run_sgp(ma3_target, all_predictors_df, lag=1)
    print("\nRunning SGP Lag 2...")
    dates2, ypred2, top7_2 = run_sgp(ma3_target, all_predictors_df, lag=2)

    # ---- Align on common test dates ----
    df1 = pd.DataFrame({'Pred_Lag1': ypred1}, index=dates1)
    df2 = pd.DataFrame({'Pred_Lag2': ypred2}, index=dates2)
    sc  = df1.join(df2, how='inner').join(raw_return.rename('Actual_Return'), how='left')

    sc['Dir_Lag1']   = np.where(sc['Pred_Lag1'] > 0, 'UP', 'Down')
    sc['Dir_Lag2']   = np.where(sc['Pred_Lag2'] > 0, 'UP', 'Down')
    sc['Dir_Actual'] = np.where(sc['Actual_Return'] > 0, 'UP', 'Down')   # raw return direction
    sc['Hit_Lag1']   = sc['Dir_Lag1'] == sc['Dir_Actual']
    sc['Agreement']  = sc['Dir_Lag1'] == sc['Dir_Lag2']

    sc_agree    = sc[sc['Agreement']]
    sc_disagree = sc[~sc['Agreement']]

    acc_all     = sc['Hit_Lag1'].mean()
    acc_agree   = sc_agree['Hit_Lag1'].mean()   if len(sc_agree)    > 0 else np.nan
    acc_disagree= sc_disagree['Hit_Lag1'].mean() if len(sc_disagree) > 0 else np.nan
    coverage    = sc['Agreement'].mean()

    print("\n" + "="*60)
    print("SGP AGREEMENT FILTER RESULTS")
    print("="*60)
    print(f"Total test days:    {len(sc)}")
    print(f"Agreement days:     {sc['Agreement'].sum()}  ({coverage:.1%})")
    print(f"Disagreement days:  {(~sc['Agreement']).sum()}")
    print(f"")
    print(f"Accuracy ALL days:          {acc_all:.1%}")
    print(f"Accuracy AGREEMENT days:    {acc_agree:.1%}  <-- high-confidence")
    print(f"Accuracy DISAGREEMENT days: {acc_disagree:.1%}  <-- skip")
    print(f"Alpha boost from filter:    +{(acc_agree - acc_all)*100:.1f}pp")

    last30 = sc.tail(30).copy()
    last30.index = last30.index.strftime('%Y-%m-%d')
    last30['Signal'] = np.where(last30['Dir_Lag1'] == 'UP', 'BUY', 'SELL')
    last30['Agree?'] = np.where(last30['Agreement'], 'YES', 'no')
    last30['Hit']    = np.where(last30['Hit_Lag1'], 'On Target', 'Miss')

    print("\n=== Last 30 Days ===")
    print(last30[['Actual_Return', 'Dir_Lag1', 'Dir_Lag2', 'Agree?', 'Signal', 'Hit']].to_string())

    acc30_all   = last30['Hit_Lag1'].mean()
    acc30_agree = last30.loc[last30['Agreement'], 'Hit_Lag1'].mean() if last30['Agreement'].any() else np.nan
    cov30       = last30['Agreement'].mean()
    print(f"\nLast 30 — All: {acc30_all:.1%} | Agreement: {acc30_agree:.1%} ({cov30:.1%} coverage)")

    # ---- Plot ----
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(f'{champion_ticker} SGP — Agreement Filter', fontsize=14, fontweight='bold')

    bars   = [acc_all*100, acc_agree*100, acc_disagree*100]
    colors = ['steelblue', 'seagreen', 'salmon']
    labels = [f'All\n(n={len(sc)})',
              f'Agreement\n(n={len(sc_agree)}, {coverage:.0%})',
              f'Disagreement\n(n={len(sc_disagree)})']
    ax1.bar(labels, bars, color=colors, alpha=0.85, edgecolor='black')
    ax1.axhline(50, color='red', linestyle='--', linewidth=1.5, label='Random (50%)')
    ax1.set_ylabel('Directional Accuracy %')
    ax1.set_title('Raw Return Directional Accuracy')
    ax1.set_ylim(30, 80); ax1.legend()
    for i, b in enumerate(bars):
        ax1.text(i, b + 0.5, f'{b:.1f}%', ha='center', fontweight='bold')

    ax2.hist(sc.loc[sc['Agreement'],  'Pred_Lag1'], bins=30, alpha=0.6, color='seagreen', label='Agreement')
    ax2.hist(sc.loc[~sc['Agreement'], 'Pred_Lag1'], bins=30, alpha=0.6, color='salmon',   label='Disagreement')
    ax2.axvline(0, color='black', linewidth=1.5)
    ax2.set_xlabel('Lag1 Prediction (z-score)'); ax2.set_title('Prediction Distribution')
    ax2.legend()

    plt.tight_layout()
    plot_path = r'C:\Users\AviShemla\AntiGravity\financial_data\SGP_Agreement_Filter.png'
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved: {plot_path}")

    sc.to_csv(r'C:\Users\AviShemla\AntiGravity\financial_data\SGP_Agreement_Scorecard.csv')
    print("Scorecard saved.")
