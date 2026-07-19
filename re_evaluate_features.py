import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

print("Loading data and new features...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

champion_ticker = 'JPM'

# Target is the Raw Daily Return % for JPM at time t
target_t = return_pivot[champion_ticker].rename('Target_JPM_t')

# Let's use a 12-month window as requested by the user previously
# Note: The data ends around 2026-05-19. Let's use 2025-05-01 to 2026-05-19.
start_date = pd.to_datetime('2025-05-01')
end_date = target_t.index.max()

print(f"\nEvaluating features for {champion_ticker} from {start_date.date()} to {end_date.date()}")

# Align predictors at t-1
predictors_t_minus_1 = all_predictors_df.shift(1)

# Add explicit causal chain variables
# DVA_Lag3, BSX_Lag2, AZO_Lag1
causal_chain = pd.DataFrame({
    'DVA_RET_Lag3': return_pivot['DVA'].shift(3),
    'BSX_RET_Lag2': return_pivot['BSX'].shift(2),
    'AZO_RET_Lag1': return_pivot['AZO'].shift(1)
})

# Combine all
combined = pd.concat([target_t, predictors_t_minus_1, causal_chain], axis=1)
combined = combined.loc[(combined.index >= start_date) & (combined.index <= end_date)].dropna(how='all', axis=1)

# Drop rows where target is NaN
combined = combined.dropna(subset=['Target_JPM_t'])

# Compute correlations
print("\nComputing correlations against Raw Daily Return %...")
corrs = combined.drop('Target_JPM_t', axis=1).corrwith(combined['Target_JPM_t'])

# Show top 15 absolute correlations
top_corrs = corrs.abs().sort_values(ascending=False).head(15)

print("\n--- TOP 15 PREDICTORS FOR JPM RAW RETURN (Last 12 Months) ---")
for feat in top_corrs.index:
    print(f"{feat:30s}: {corrs[feat]:+.4f}")

print("\n--- CAUSAL CHAIN FEATURES ---")
for feat in ['DVA_RET_Lag3', 'BSX_RET_Lag2', 'AZO_RET_Lag1']:
    if feat in corrs:
        print(f"{feat:30s}: {corrs[feat]:+.4f}")

print("\n--- NEW SECTOR INDICATORS (JPM) ---")
for feat in [f'{champion_ticker}_SEC_REG', f'{champion_ticker}_SEC_MOM']:
    if feat in corrs:
        print(f"{feat:30s}: {corrs[feat]:+.4f}")
