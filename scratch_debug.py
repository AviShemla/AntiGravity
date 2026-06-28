import pandas as pd
import numpy as np
import sys
sys.path.insert(0, "C:/Users/AviShemla/AntiGravity")
from data_loader import load_predictors

all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
target_t = return_pivot["GOOG"].loc["2025-05-01":"2026-05-11"]
target_dir = (target_t > 0).astype(float)
target_dir.loc[target_t.isna()] = np.nan
target_dir = target_dir.rename('Target_DIR')

data_with_future = pd.concat([target_dir, target_t], axis=1).loc["2025-05-01":"2026-05-11"]
historical_data = data_with_future.dropna(subset=['Target_DIR'])

split_idx = len(historical_data) - 30
train_data = historical_data.iloc[:split_idx]
test_data = historical_data.iloc[split_idx:]
future_data = data_with_future.loc[["2026-05-11"]]
test_data = pd.concat([test_data, future_data])

returns_full = data_with_future['GOOG'].fillna(0.0).values / 100.0
inferred_volatility = np.zeros(len(returns_full))
sv_vol_shifted = np.roll(inferred_volatility, 1)
sv_vol_shifted[0] = inferred_volatility[0]

sv_vol_test = sv_vol_shifted[split_idx:]

print(f"data_with_future len: {len(data_with_future)}")
print(f"historical_data len: {len(historical_data)}")
print(f"test_data len: {len(test_data)}")
print(f"returns_full len: {len(returns_full)}")
print(f"sv_vol_test len: {len(sv_vol_test)}")
