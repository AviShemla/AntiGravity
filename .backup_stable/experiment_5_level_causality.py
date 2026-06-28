import pandas as pd
import numpy as np
import os
import sys
from sklearn.linear_model import LogisticRegression
import time

sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors

print("Loading data for 5-Level Causality Experiment...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

start_date = pd.to_datetime('2025-05-01')
end_date = return_pivot.index.max()

returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)].dropna(axis=1, how='all')
shifted_preds = all_predictors_df.shift(1).loc[start_date:end_date]

tickers = returns_df.columns.tolist()
print(f"\nStarting screening across {len(tickers)} tickers...")
print(f"Timeframe: {start_date.date()} to {end_date.date()}")
print(f"Out-of-Sample Test: Last 30 days\n")

results = []
start_time = time.time()

# Pre-calculate shifted returns to speed up causal chain discovery
shifted_returns_1 = returns_df.shift(1)

def find_best_lag1(target_series, predictor_df_shifted):
    # Align and drop NaNs
    valid_idx = target_series.notna()
    tgt = target_series[valid_idx]
    preds = predictor_df_shifted.loc[valid_idx]
    
    # We only want to correlate where preds has data
    if len(tgt) < 50: 
        return None
        
    corrs = preds.corrwith(tgt)
    return corrs.abs().idxmax()

for i, ticker in enumerate(tickers):
    if (i+1) % 25 == 0:
        print(f"  Processed {i+1}/{len(tickers)} tickers...")
        
    try:
        target_t = returns_df[ticker].rename('Target_t')
        
        # 1. 5-Level Causal Chain Discovery
        lag1 = find_best_lag1(target_t, shifted_returns_1)
        if not lag1: continue
        lag2 = find_best_lag1(returns_df[lag1], shifted_returns_1)
        if not lag2: continue
        lag3 = find_best_lag1(returns_df[lag2], shifted_returns_1)
        if not lag3: continue
        lag4 = find_best_lag1(returns_df[lag3], shifted_returns_1)
        if not lag4: continue
        lag5 = find_best_lag1(returns_df[lag4], shifted_returns_1)
        if not lag5: continue
        
        # 2. Top Technicals
        comb = pd.concat([target_t, shifted_preds], axis=1).dropna(how='all', axis=1).dropna(subset=['Target_t'])
        if len(comb) < 50: continue
        
        corrs = comb.drop('Target_t', axis=1).corrwith(comb['Target_t'])
        tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
        top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()
        
        # 3. Build Feature Matrix
        chain_5 = returns_df[lag5].shift(5).rename(f'{lag5}_Lag5')
        chain_4 = returns_df[lag4].shift(4).rename(f'{lag4}_Lag4')
        chain_3 = returns_df[lag3].shift(3).rename(f'{lag3}_Lag3')
        chain_2 = returns_df[lag2].shift(2).rename(f'{lag2}_Lag2')
        chain_1 = returns_df[lag1].shift(1).rename(f'{lag1}_Lag1')
        
        feat_cols = top_3_tech + [chain_5.name, chain_4.name, chain_3.name, chain_2.name, chain_1.name]
        
        # Sector regimes
        sec_reg_name = f'{ticker}_SEC_REG'
        sec_mom_name = f'{ticker}_SEC_MOM'
        components = [
            (target_t > 0).astype(int).rename('Target_DIR'),
            shifted_preds[top_3_tech],
            chain_5, chain_4, chain_3, chain_2, chain_1
        ]
        
        if sec_reg_name in shifted_preds.columns:
            components.append(shifted_preds[sec_reg_name].rename(f'{sec_reg_name}_t-1'))
            feat_cols.append(f'{sec_reg_name}_t-1')
        if sec_mom_name in shifted_preds.columns:
            components.append(shifted_preds[sec_mom_name].rename(f'{sec_mom_name}_t-1'))
            feat_cols.append(f'{sec_mom_name}_t-1')
            
        data = pd.concat(components, axis=1).dropna()
        if len(data) < 100:
            continue
            
        # 4. Train/Test Split
        split_idx = len(data) - 30
        train_data = data.iloc[:split_idx]
        test_data = data.iloc[split_idx:]
        
        X_train = train_data[feat_cols].values
        y_train = train_data['Target_DIR'].values
        X_test = test_data[feat_cols].values
        y_test = test_data['Target_DIR'].values
        
        # Standardize
        Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
        X_train_s = (X_train - Xm) / Xs
        X_test_s = (X_test - Xm) / Xs
        
        # 5. Fast Logistic Regression
        clf = LogisticRegression(C=1.0, random_state=42)
        clf.fit(X_train_s, y_train)
        preds = clf.predict(X_test_s)
        
        acc = np.mean(preds == y_test)
        
        results.append({
            'Ticker': ticker,
            'OOS_Accuracy': acc,
            'Lag5': lag5,
            'Lag4': lag4,
            'Lag3': lag3,
            'Lag2': lag2,
            'Lag1': lag1
        })
        
    except Exception as e:
        # Silently skip tickers with data errors
        continue

elapsed = time.time() - start_time
print(f"\n5-Level Screening complete in {elapsed:.1f} seconds!")

# --- AGGREGATE RESULTS ---
res_df = pd.DataFrame(results).sort_values(by='OOS_Accuracy', ascending=False)
res_df['OOS_Accuracy'] = (res_df['OOS_Accuracy'] * 100).round(1)

out_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Experiment_5Lag_Results.csv'
res_df.to_csv(out_path, index=False)

print("\n=== TOP 15 MOST PREDICTABLE TICKERS (5-LAG MODEL) ===")
print("Based on 30-Day Out-of-Sample Raw Directional Accuracy (Logistic Regression)")
print(res_df.head(15).to_string(index=False))

print(f"\nFull 5-Lag results saved to: {out_path}")
