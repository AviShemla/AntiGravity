import pandas as pd
import numpy as np
import os
import itertools
from sklearn.linear_model import LogisticRegression
import time

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
MACRO_ETFS = ['SPY', 'TLT', 'GLD', 'UUP']

def screen_hybrid_matrix(target_etf):
    print(f"--- Starting Hybrid Screener for {target_etf} ---")
    
    file_path = os.path.join(BASE_DIR, f'{target_etf}_Hybrid_Matrix.csv')
    if not os.path.exists(file_path):
        print(f"Error: Could not find matrix for {target_etf}")
        return
        
    df = pd.read_csv(file_path, index_col=0)
    
    target_col = f'{target_etf}_Direction'
    if target_col not in df.columns:
        print(f"Error: Target column {target_col} not found.")
        return
        
    # Isolate all available lag features (drop the target Returns and Directions)
    valid_cols = [c for c in df.columns if c not in [target_col, f'{target_etf}_Return_%']]
    
    # Split into Macro vs Micro features
    macro_features = [c for c in valid_cols if any(c.startswith(m + '_') for m in MACRO_ETFS) or c in ['VIX_Close', 'Market_Fear_Level', f'{target_etf}_Daily_STDEV']]
    micro_features = [c for c in valid_cols if c not in macro_features and not c.startswith(target_etf + '_')]
    if len(micro_features) < 2:
        print("Not enough micro features. Falling back to target ETF lags as micro features.")
        micro_features = [c for c in valid_cols if c.startswith(target_etf + '_Lag')]
        
    print(f"Total Macro Features: {len(macro_features)}")
    print(f"Total Micro Features: {len(micro_features)}")
    
    # We will test combinations of 1 Macro + 2 Micro, or 2 Macro + 1 Micro
    # To keep it fast, we will first filter for features that have some basic correlation with the target
    y = df[target_col]
    X_all = df[valid_cols]
    
    # Calculate simple correlation with Target Return (not direction) to prune useless features
    target_ret_col = f'{target_etf}_Return_%'
    corrs = df[valid_cols].corrwith(df[target_ret_col]).abs().sort_values(ascending=False)
    
    # Take Top 15 Macro and Top 15 Micro to reduce combinatorial explosion
    top_macro = [c for c in corrs.index if c in macro_features][:15]
    top_micro = [c for c in corrs.index if c in micro_features][:15]
    
    # Generate Hybrid Combinations (2 Macro + 2 Micro = 4-factor chains)
    macro_pairs = list(itertools.combinations(top_macro, 2))
    micro_pairs = list(itertools.combinations(top_micro, 2))
    
    combinations = [m + mi for m in macro_pairs for mi in micro_pairs]
    print(f"Testing {len(combinations)} hybrid causal combinations...")
    
    results = []
    
    # Train/Test Split (Last 60 days for OOS testing)
    split_idx = len(df) - 60
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]
    
    y_train = train_df[target_col].values
    y_test = test_df[target_col].values
    
    start_time = time.time()
    count = 0
    
    for combo in combinations:
        count += 1
        if count % 2000 == 0:
            print(f"  ...processed {count}/{len(combinations)}")
            
        X_train = train_df[list(combo)].values
        X_test = test_df[list(combo)].values
        
        # Scale
        Xm = X_train.mean(axis=0)
        Xs = X_train.std(axis=0) + 1e-8
        X_train_s = (X_train - Xm) / Xs
        X_test_s = (X_test - Xm) / Xs
        
        clf = LogisticRegression(C=1.0, random_state=42, max_iter=1000)
        clf.fit(X_train_s, y_train)
        
        preds = clf.predict(X_test_s)
        acc = np.mean(preds == y_test)
        
        if acc > 0.55: # Only save interesting chains
            probs = clf.predict_proba(X_test_s)
            
            res = {
                'Target': target_etf,
                'OOS_Accuracy': round(acc * 100, 1),
                'Macro_1': combo[0],
                'Macro_2': combo[1],
                'Micro_1': combo[2],
                'Micro_2': combo[3]
            }
            results.append(res)
            
    elapsed = time.time() - start_time
    print(f"Screening completed in {elapsed:.1f} seconds!")
    
    if not results:
        print("No combinations achieved >55% OOS accuracy.")
        return
        
    res_df = pd.DataFrame(results).sort_values(by='OOS_Accuracy', ascending=False)
    
    out_path = os.path.join(BASE_DIR, f'{target_etf}_Hybrid_Screener_Results.csv')
    res_df.to_csv(out_path, index=False)
    
    print("\n=== TOP 10 HYBRID CAUSAL CHAINS ===")
    print(res_df.head(10).to_string(index=False))
    print(f"\nSaved to: {out_path}")

if __name__ == '__main__':
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else 'XLK'
    screen_hybrid_matrix(target)
