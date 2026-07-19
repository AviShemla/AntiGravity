import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

# 1. Load Data
print("Loading data...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
champion_ticker = 'TGT'

# 2. Filter Dates
# Max date: 2026-04-30
# Min date: 2026-01-30 (3 months)
start_date = pd.to_datetime('2026-01-30')
end_date = pd.to_datetime('2026-04-30')

# We use RAW returns for all tickers as our feature space, per user request
# return_pivot contains the raw Daily_Return_% for all tickers
returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)].dropna(axis=1, how='all')

print(f"\nFiltered dataset: {returns_df.index.min().date()} to {returns_df.index.max().date()} ({len(returns_df)} days)")
print(f"Available tickers: {len(returns_df.columns)}")

# 3. Chain Discovery Algorithm
# To find a cascade YYY(t-3) -> ZZZ(t-2) -> XXX(t-1) -> Target(t)
# We can just repeatedly find the best Lag 1 predictor for the subsequent node.

def find_best_lag1_predictors(target_series, predictor_df, top_n=5):
    """Finds the top_n tickers whose t-1 values correlate most with target_series at t."""
    # Align target(t) with predictors(t-1)
    shifted_predictors = predictor_df.shift(1)
    combined = pd.concat([target_series.rename('Target'), shifted_predictors], axis=1).dropna()
    
    if len(combined) < 30:
        return []
        
    corrs = combined.drop('Target', axis=1).corrwith(combined['Target'])
    # Get absolute correlations, sort descending
    top_corrs = corrs.abs().sort_values(ascending=False).head(top_n)
    
    # Return actual correlations (with sign) for the top absolute ones
    result = []
    for ticker in top_corrs.index:
        result.append({'Ticker': ticker, 'Correlation': corrs[ticker]})
    return result

print(f"\n=== Discovering Causal Chains for {champion_ticker} ===")

# Step 1: Find XXX (Lag 1 -> Target)
print(f"\n[Step 1] Finding Lag 1 Predictors (XXX_t-1 -> {champion_ticker}_t)")
target_t = returns_df[champion_ticker]
lag1_candidates = find_best_lag1_predictors(target_t, returns_df, top_n=3)

for idx, lag1 in enumerate(lag1_candidates):
    xxx = lag1['Ticker']
    corr1 = lag1['Correlation']
    print(f"\n  Chain Pathway {idx+1}: starting with {xxx} (Corr: {corr1:.3f})")
    
    # Step 2: Find ZZZ (Lag 2 -> XXX)
    # Equivalently: find what predicts XXX(t) using lag 1
    xxx_t = returns_df[xxx]
    lag2_candidates = find_best_lag1_predictors(xxx_t, returns_df, top_n=1)
    if not lag2_candidates:
        continue
    zzz = lag2_candidates[0]['Ticker']
    corr2 = lag2_candidates[0]['Correlation']
    
    # Step 3: Find YYY (Lag 3 -> ZZZ)
    # Equivalently: find what predicts ZZZ(t) using lag 1
    zzz_t = returns_df[zzz]
    lag3_candidates = find_best_lag1_predictors(zzz_t, returns_df, top_n=1)
    if not lag3_candidates:
        continue
    yyy = lag3_candidates[0]['Ticker']
    corr3 = lag3_candidates[0]['Correlation']
    
    print(f"  Resulting Chain:")
    print(f"    Lag 3 Leader: {yyy}  --[corr: {corr3:+.3f}]-->")
    print(f"    Lag 2 Bridge: {zzz}  --[corr: {corr2:+.3f}]-->")
    print(f"    Lag 1 Peer  : {xxx}  --[corr: {corr1:+.3f}]-->")
    print(f"    Target      : {champion_ticker}")
    
    # Now, let's verify if YYY(t-3) actually correlates with Target(t) directly
    # and if the whole regression model makes sense.
    target_combined = pd.DataFrame({
        'Target_t': returns_df[champion_ticker],
        f'{xxx}_t-1': returns_df[xxx].shift(1),
        f'{zzz}_t-2': returns_df[zzz].shift(2),
        f'{yyy}_t-3': returns_df[yyy].shift(3)
    }).dropna()
    
    direct_corr_3 = target_combined['Target_t'].corr(target_combined[f'{yyy}_t-3'])
    direct_corr_2 = target_combined['Target_t'].corr(target_combined[f'{zzz}_t-2'])
    print(f"    Direct correlation check to {champion_ticker}_t:")
    print(f"      {yyy}_t-3 directly to {champion_ticker}_t : {direct_corr_3:+.3f}")
    print(f"      {zzz}_t-2 directly to {champion_ticker}_t : {direct_corr_2:+.3f}")

print("\nAnalysis complete.")
