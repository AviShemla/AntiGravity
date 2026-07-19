import pandas as pd
import numpy as np
import os
import sys
from sklearn.linear_model import LogisticRegression
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

print("Loading data for Adaptive Depth Screener...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

start_date = pd.to_datetime('2025-05-01')
end_date = return_pivot.index.max()

returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)].dropna(axis=1, how='all')
shifted_preds = all_predictors_df.shift(1).loc[start_date:end_date]

tickers = returns_df.columns.tolist()
print(f"\nStarting Adaptive Depth Screening (Lags 3-5) across {len(tickers)} tickers...")
print(f"Timeframe: {start_date.date()} to {end_date.date()}")
print(f"Out-of-Sample Test: Last 30 days\n")

results = []
start_time = time.time()

shifted_returns_1 = returns_df.shift(1)

def find_best_lag1(target_series, predictor_df_shifted):
    valid_idx = target_series.notna()
    tgt = target_series[valid_idx]
    preds = predictor_df_shifted.loc[valid_idx]
    if len(tgt) < 50: return None
    corrs = preds.corrwith(tgt)
    return corrs.abs().idxmax()

def evaluate_depth(ticker, target_t, chain_lags, top_3_tech):
    depth = len(chain_lags)
    feat_cols = top_3_tech.copy()
    components = [(target_t > 0).astype(int).rename('Target_DIR'), shifted_preds[top_3_tech]]
    
    for d in range(depth, 0, -1):
        lag_name = chain_lags[d]
        chain_col = returns_df[lag_name].shift(d).rename(f'{lag_name}_Lag{d}')
        components.append(chain_col)
        feat_cols.append(chain_col.name)
        
    sec_reg_name = f'{ticker}_SEC_REG'
    sec_mom_name = f'{ticker}_SEC_MOM'
    if sec_reg_name in shifted_preds.columns:
        components.append(shifted_preds[sec_reg_name].rename(f'{sec_reg_name}_t-1'))
        feat_cols.append(f'{sec_reg_name}_t-1')
    if sec_mom_name in shifted_preds.columns:
        components.append(shifted_preds[sec_mom_name].rename(f'{sec_mom_name}_t-1'))
        feat_cols.append(f'{sec_mom_name}_t-1')
        
    data = pd.concat(components, axis=1).dropna()
    if len(data) < 100: return 0.0
    
    split_idx = len(data) - 30
    train_data = data.iloc[:split_idx]
    test_data = data.iloc[split_idx:]
    
    X_train = train_data[feat_cols].values
    y_train = train_data['Target_DIR'].values
    X_test = test_data[feat_cols].values
    y_test = test_data['Target_DIR'].values
    
    Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
    X_train_s = (X_train - Xm) / Xs
    X_test_s = (X_test - Xm) / Xs
    
    clf = LogisticRegression(C=1.0, random_state=42)
    clf.fit(X_train_s, y_train)
    preds = clf.predict(X_test_s)
    return np.mean(preds == y_test)

for i, ticker in enumerate(tickers):
    if (i+1) % 25 == 0:
        print(f"  Processed {i+1}/{len(tickers)} tickers...")
        
    try:
        target_t = returns_df[ticker].rename('Target_t')
        
        lag1 = find_best_lag1(target_t, shifted_returns_1)
        if not lag1: continue
        lag2 = find_best_lag1(returns_df[lag1], shifted_returns_1)
        if not lag2: continue
        lag3 = find_best_lag1(returns_df[lag2], shifted_returns_1)
        if not lag3: continue
        
        chain_lags = {1: lag1, 2: lag2, 3: lag3}
        
        comb = pd.concat([target_t, shifted_preds], axis=1).dropna(how='all', axis=1).dropna(subset=['Target_t'])
        if len(comb) < 50: continue
        corrs = comb.drop('Target_t', axis=1).corrwith(comb['Target_t'])
        tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
        top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()
        
        acc_3 = evaluate_depth(ticker, target_t, chain_lags, top_3_tech)
        
        lag4 = find_best_lag1(returns_df[lag3], shifted_returns_1)
        acc_4 = 0.0
        if lag4:
            chain_lags[4] = lag4
            acc_4 = evaluate_depth(ticker, target_t, chain_lags, top_3_tech)
            
        lag5 = None
        acc_5 = 0.0
        if lag4:
            lag5 = find_best_lag1(returns_df[lag4], shifted_returns_1)
            if lag5:
                chain_lags[5] = lag5
                acc_5 = evaluate_depth(ticker, target_t, chain_lags, top_3_tech)
                
        best_acc = max(acc_3, acc_4, acc_5)
        
        if best_acc == 0:
            continue
            
        best_depth = 3
        if best_acc == acc_5: best_depth = 5
        elif best_acc == acc_4: best_depth = 4
        
        res = {
            'Ticker': ticker,
            'OOS_Accuracy': best_acc,
            'Depth': best_depth,
            'Lag5': lag5 if best_depth == 5 else "",
            'Lag4': lag4 if best_depth >= 4 else "",
            'Lag3': lag3,
            'Lag2': lag2,
            'Lag1': lag1
        }
        results.append(res)
        
    except Exception as e:
        continue

elapsed = time.time() - start_time
print(f"\nAdaptive Depth Screening complete in {elapsed:.1f} seconds!")

res_df = pd.DataFrame(results).sort_values(by='OOS_Accuracy', ascending=False)
res_df['OOS_Accuracy'] = (res_df['OOS_Accuracy'] * 100).round(1)

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'Fast_Screener_Results.csv')
res_df.to_csv(out_path, index=False)

print("\n=== TOP 15 MOST PREDICTABLE TICKERS ===")
print("Based on 30-Day Out-of-Sample Raw Directional Accuracy (Adaptive Depth)")
print(res_df.head(15).to_string(index=False))

print(f"\nFull Adaptive results saved to: {out_path}")
