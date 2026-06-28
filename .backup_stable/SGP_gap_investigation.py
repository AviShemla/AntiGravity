# =============================================================================
# MA3 GAP INVESTIGATION
# Decomposes the SGP's 28% R² into:
#   (A) Free autocorrelation from the MA3 structure (AR baseline)
#   (B) Genuine additional alpha from sector features
# =============================================================================
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.cluster import KMeans
import pymc as pm
import matplotlib.pyplot as plt
import os

os.environ["PYTENSOR_FLAGS"] = "cxx="

input_file      = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Clean_Advanced_Analysis.csv'
champion_ticker = 'JPM'

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])
df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])

df['RAS_Signal_Num'] = df['RAS_Signal'].map({'BUY': 1, 'HOLD': 0, 'SELL': -1}).fillna(0)
df['Market_Fear_Level_Num'] = df['Market_Fear_Level'].map({'Complacency / Calm': 0, 'High Volatility': 1}).fillna(0)

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
    predictors_list.append(pd.DataFrame({
        f'{ticker}_RET_ADJ':  std_adj_returns[ticker],
        f'{ticker}_RSI':      rsi_pivot[ticker],
        f'{ticker}_ADX':      adx_pivot[ticker],
        f'{ticker}_PLUS_DI':  plus_di_pivot[ticker],
        f'{ticker}_MINUS_DI': minus_di_pivot[ticker],
        f'{ticker}_ATR':      atr_pivot[ticker],
        f'{ticker}_RAS':      ras_pivot[ticker],
    }))
all_predictors_df = pd.concat(predictors_list, axis=1)
macro_df = df.drop_duplicates(subset=['Date']).set_index('Date')[['VIX_Close', 'Market_Fear_Level_Num']]
all_predictors_df = pd.concat([all_predictors_df, macro_df], axis=1)

raw_return = return_pivot[champion_ticker]
std_adj    = std_adj_returns[champion_ticker]
ma3_target = std_adj.rolling(3).mean()

lag = 1
target     = ma3_target.copy()
shifted    = all_predictors_df.shift(lag)
data       = pd.concat([target, shifted], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
data.columns = ['target'] + list(all_predictors_df.columns)

y_all      = data['target'].values
X_pool     = data.drop(columns=['target'])
dates_all  = data.index
split      = int(len(data) * 0.8)

y_train, y_test       = y_all[:split], y_all[split:]
Xp_train, Xp_test     = X_pool.iloc[:split], X_pool.iloc[split:]
dates_test            = dates_all[split:]

print(f"\nTest period: {dates_test[0].date()} to {dates_test[-1].date()} ({len(y_test)} days)")
print(f"Total R² denominator (variance of y_test): {y_test.var():.4f}")

# =================================================================
# TEST A: AR(1) Baseline — trivial autocorrelation of MA3
# =================================================================
print("\n" + "="*60)
print("TEST A: AR(1) Baseline (trivial MA3 autocorrelation)")
print("="*60)

# MA3(t-1) aligned to test set
ma3_lag1 = ma3_target.shift(1)
aligned = pd.concat([target.rename('target'), ma3_lag1.rename('ma3_lag1')], axis=1).dropna()
# Use the same train/test split dates
aligned_train = aligned.loc[aligned.index < dates_test[0]]
aligned_test  = aligned.loc[aligned.index >= dates_test[0]]

ar_fit = LinearRegression().fit(aligned_train[['ma3_lag1']], aligned_train['target'])
y_pred_ar = ar_fit.predict(aligned_test[['ma3_lag1']])
y_test_ar = aligned_test['target'].values

ss_res_ar = np.sum((y_test_ar - y_pred_ar)**2)
ss_tot_ar = np.sum((y_test_ar - y_test_ar.mean())**2)
r2_ar = 1 - ss_res_ar / ss_tot_ar

ar_coef = ar_fit.coef_[0]
dir_acc_ar = np.mean(np.sign(y_pred_ar) == np.sign(raw_return.loc[aligned_test.index].values)) * 100

print(f"AR(1) coefficient: {ar_coef:.4f}  (theoretical: 0.6667)")
print(f"AR(1) R² on MA3 target:      {r2_ar:.4f}  ({r2_ar*100:.1f}%)")
print(f"AR(1) directional acc (raw): {dir_acc_ar:.1f}%")

# =================================================================
# TEST B: MA3 Residual — the genuinely new info in each day
# =================================================================
print("\n" + "="*60)
print("TEST B: Residual = MA3(t) - AR(1) prediction  (new info only)")
print("="*60)

# residual ≈ r(t)/3 - r(t-3)/3 — the truly unknowable part
residual = aligned_test['target'].values - y_pred_ar
var_explained_by_ar = 1 - np.var(residual) / np.var(y_test_ar)
print(f"Fraction of MA3 variance explained by AR alone: {var_explained_by_ar:.1%}")
print(f"Fraction that is genuinely NEW (residual):      {1-var_explained_by_ar:.1%}")
print(f"Residual mean: {residual.mean():.4f}  std: {residual.std():.4f}")

# Residual directional accuracy (can sector features predict this?)
# We approximate: sign(residual) ≈ sign(r(t)) on many days
raw_test = raw_return.loc[aligned_test.index].values
corr_residual_raw = np.corrcoef(residual, raw_test)[0, 1]
print(f"\nCorrelation between residual and raw return: {corr_residual_raw:.4f}")
print("(If ~0.33, residual is capturing ~r(t)/3 as expected)")

# =================================================================
# TEST C: SGP on RAW daily return target (not MA3)
# =================================================================
print("\n" + "="*60)
print("TEST C: SGP on RAW daily return target (not MA3)")
print("="*60)

raw_target = std_adj.copy()   # return/stdev but NOT smoothed
shifted2   = all_predictors_df.shift(lag)
data2      = pd.concat([raw_target, shifted2], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
data2.columns = ['target'] + list(all_predictors_df.columns)

y2_all = data2['target'].values
X2pool = data2.drop(columns=['target'])
split2 = int(len(data2) * 0.8)
y2_train, y2_test = y2_all[:split2], y2_all[split2:]
Xp2_train, Xp2_test = X2pool.iloc[:split2], X2pool.iloc[split2:]

corrs2 = Xp2_train.corrwith(pd.Series(y2_train, index=Xp2_train.index))
top7_2 = corrs2.abs().sort_values(ascending=False).head(7).index.tolist()
print(f"Top 7 for raw target: {top7_2}")

X2t = Xp2_train[top7_2].values;  X2e = Xp2_test[top7_2].values
X2m = X2t.mean(0);  X2s = X2t.std(0) + 1e-8
X2t_s = (X2t - X2m) / X2s;  X2e_s = (X2e - X2m) / X2s

with pm.Model():
    ls  = pm.Gamma("ls", alpha=2, beta=1, shape=7)
    eta = pm.HalfNormal("eta", sigma=float(np.std(y2_train)))
    cov = eta**2 * pm.gp.cov.ExpQuad(input_dim=7, ls=ls)
    Xu  = KMeans(n_clusters=min(150, len(X2t_s)), random_state=42, n_init=5).fit(X2t_s).cluster_centers_
    gp  = pm.gp.MarginalApprox(cov_func=cov, approx="FITC")
    sig = pm.HalfNormal("sigma", sigma=float(np.std(y2_train)))
    _   = gp.marginal_likelihood("y_obs", X=X2t_s, Xu=Xu, y=y2_train, sigma=sig)
    tr  = pm.sample(draws=300, tune=300, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
    fp  = gp.conditional("f_pred", Xnew=X2e_s)
    pp  = pm.sample_posterior_predictive(tr, var_names=["f_pred"], progressbar=False)

y2_pred = pp.posterior_predictive["f_pred"].mean(dim=["chain", "draw"]).values
ss_res2 = np.sum((y2_test - y2_pred)**2)
ss_tot2 = np.sum((y2_test - y2_test.mean())**2)
r2_raw  = 1 - ss_res2 / ss_tot2

dates2_test = data2.index[split2:]
raw2_actual = return_pivot[champion_ticker].reindex(dates2_test).values
dir_acc_raw_sgp = np.mean(np.sign(y2_pred) == np.sign(raw2_actual)) * 100

print(f"\nSGP R² on raw adj return target:  {r2_raw:.4f}  ({r2_raw*100:.1f}%)")
print(f"SGP directional acc (raw return): {dir_acc_raw_sgp:.1f}%")

# =================================================================
# SUMMARY
# =================================================================
print("\n" + "="*60)
print("INVESTIGATION SUMMARY")
print("="*60)
print(f"SGP R² on MA3 target:              ~28-30%   (our champion model)")
print(f"AR(1) baseline R² on MA3 target:    {r2_ar*100:.1f}%    (trivial autocorrelation)")
print(f"Genuine alpha above AR baseline:    {max(0, 0.28-r2_ar)*100:.1f}%    (SGP R² - AR R²)")
print(f"AR(1) raw-return directional acc:   {dir_acc_ar:.1f}%")
print(f"SGP  raw-return directional acc:    {dir_acc_raw_sgp:.1f}%")
print(f"Fraction of MA3 variance that is NEW (unpredictable): {(1-var_explained_by_ar)*100:.1f}%")
print(f"\nCONCLUSION:")
if r2_ar > 0.20:
    print("  The MA3 structure provides substantial FREE R² via autocorrelation.")
    print("  The SGP's R² is partially (or largely) explained by this structural effect.")
    print("  True predictive alpha should be measured on the AR-RESIDUAL or raw return.")
else:
    print("  AR baseline is low — SGP has genuine predictive power above autocorrelation.")
