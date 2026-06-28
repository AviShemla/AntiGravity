# =============================================================================
# MODEL: Bayesian Logistic Regression (BLR_workflow.py)
# Target: binary direction (1 = positive raw return, 0 = negative)
# Approach: Bernoulli likelihood, logistic link, Normal priors
# Uses shared data_loader.py for schema-resilient data loading.
# =============================================================================
import pandas as pd
import numpy as np
import pymc as pm
import pytensor.tensor as pt
import os
import sys
sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors, prepare_sgp_data

os.environ["PYTENSOR_FLAGS"] = "cxx="

champion_ticker = 'JPM'

# ---- Load data ----
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
raw_return = return_pivot[champion_ticker]


def run_blr_experiment(raw_return_series, predictors_df, lag, exp_name):
    print(f"\n--- {exp_name} (Lag {lag}) ---")

    # Binary target: 1 = next-day positive return, 0 = negative
    binary_target = (raw_return_series > 0).astype(float).rename('direction')

    # Use shared prepare_sgp_data with binary target
    y_train, Xt_s, y_test, Xe_s, dates_test, top7, Xm, Xs = prepare_sgp_data(
        binary_target, predictors_df, lag=lag, top_k=7)

    y_train = y_train.astype(int)
    y_test  = y_test.astype(int)

    print(f"Top 7: {top7}")
    print(f"Train: {len(y_train)} rows | Test: {len(y_test)} rows")

    # === Bayesian Logistic Regression ===
    with pm.Model() as blr:
        alpha   = pm.Normal("alpha", mu=0, sigma=2.5)
        beta    = pm.Normal("beta",  mu=0, sigma=2.5, shape=7)
        logit_p = alpha + pt.dot(Xt_s, beta)
        _       = pm.Bernoulli("y_obs", logit_p=logit_p, observed=y_train)
        trace   = pm.sample(draws=500, tune=300, chains=2,
                            target_accept=0.9, random_seed=42, progressbar=False)

    alpha_m    = float(trace.posterior["alpha"].mean().values)
    beta_m     = trace.posterior["beta"].mean(dim=["chain", "draw"]).values
    logit_pred = alpha_m + Xe_s @ beta_m
    p_pred     = 1 / (1 + np.exp(-logit_pred))
    y_pred     = (p_pred > 0.5).astype(int)

    accuracy  = (y_pred == y_test).mean()

    # High-confidence days: model is very sure (p > 0.65 or p < 0.35)
    high_conf = (p_pred > 0.65) | (p_pred < 0.35)
    acc_high  = (y_pred[high_conf] == y_test[high_conf]).mean() if high_conf.sum() > 0 else np.nan
    coverage  = high_conf.mean()

    print(f"Overall directional accuracy:             {accuracy:.1%}")
    print(f"High-confidence accuracy (p>0.65/<0.35): {acc_high:.1%}  ({coverage:.1%} of days)")

    # 30-day scorecard
    raw_actual = raw_return_series.reindex(dates_test)
    sc = pd.DataFrame({
        'Actual_Return_%': raw_actual.values,
        'P_Up':            p_pred,
        'Predicted_Dir':   np.where(y_pred == 1, 'BUY', 'SELL'),
        'Actual_Dir':      np.where(y_test == 1, 'UP',  'Down'),
        'Confidence':      np.where(high_conf, 'High', 'Low'),
        'Hit':             np.where(y_pred == y_test, 'On Target', 'Miss'),
    }, index=dates_test)

    last30    = sc.tail(30)
    acc_last30 = (last30['Hit'] == 'On Target').mean()
    print(f"Last 30-day accuracy: {acc_last30:.1%}")

    return {
        'Experiment': exp_name, 'Lag': lag,
        'Overall_Accuracy':   round(accuracy, 4),
        'HighConf_Accuracy':  round(float(acc_high), 4) if not np.isnan(acc_high) else np.nan,
        'HighConf_Coverage':  round(float(coverage), 4),
        'Last30_Accuracy':    round(acc_last30, 4),
        'Top7':               ", ".join(top7)
    }, last30


if __name__ == '__main__':
    results = []

    res1, sc1 = run_blr_experiment(raw_return, all_predictors_df, 1, f"{champion_ticker} BLR")
    results.append(res1)

    res2, sc2 = run_blr_experiment(raw_return, all_predictors_df, 2, f"{champion_ticker} BLR")
    results.append(res2)

    print("\n\n=== BLR Workflow Summary ===")
    summary = pd.DataFrame(results)
    print(summary.to_string(index=False))

    print("\n=== Last 30 Days Scorecard (Lag 1) ===")
    print(sc1.round(3).to_string())

    csv_path = r'C:\Users\AviShemla\AntiGravity\financial_data\BLR_JPM_Summary.csv'
    summary.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")
