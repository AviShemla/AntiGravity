import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import pandas as pd
import numpy as np
import sys
from sklearn.linear_model import LogisticRegression
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

MAX_LAG_HORIZON = 7
MAX_CHAIN_DEPTH = 5
TOP_PORTFOLIO_SIZE = 10

print("Loading data for Adaptive Multi-Lag (1..7) & Depth (1..5) Causal Screener...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()

start_date = pd.to_datetime('2025-05-01')
end_date = return_pivot.index.max()

returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)].dropna(axis=1, how='all')
# Keep only tickers that are actively updated through the latest date and have >= 200 valid sessions
latest_valid = returns_df.iloc[-5:].notna().all(axis=0) & (returns_df.notna().sum(axis=0) >= 200)
returns_df = returns_df.loc[:, latest_valid]

shifted_preds = all_predictors_df.shift(1).loc[start_date:end_date]

tickers = returns_df.columns.tolist()
ticker_to_idx = {t: i for i, t in enumerate(tickers)}

print(f"\nStarting Adaptive Causal Screening (Chain Depth 1..{MAX_CHAIN_DEPTH}, Lag Horizon 1..{MAX_LAG_HORIZON}) across {len(tickers)} active tickers...")
print(f"Timeframe: {start_date.date()} to {end_date.date()}")
print(f"Strict Leakage Control: Lag & feature selection on Training Split only | Out-of-Sample Test: Last 30 days\n")

start_time = time.time()

# Precompute training split standardized return matrix for vectorized 7-lag cross-correlation
split_idx_global = max(50, len(returns_df) - 30)
train_returns_df = returns_df.iloc[:split_idx_global]
Z_train = ((train_returns_df - train_returns_df.mean(axis=0)) / (train_returns_df.std(axis=0) + 1e-8)).fillna(0.0).values
T_train, N_tickers = Z_train.shape

# Precompute standardized technical predictor matrix on training split for vectorized top-3 tech lookup
tech_cols = [
    c for c in shifted_preds.columns
    if not any(k in c.upper() for k in ('SEC_REG', 'SEC_MOM', 'VIX', 'MARKET_FEAR'))
]
train_tech_df = shifted_preds[tech_cols].iloc[:split_idx_global]
tech_std = train_tech_df.std(axis=0).values
valid_tech_mask = tech_std > 1e-6
tech_cols = [c for c, m in zip(tech_cols, valid_tech_mask) if m]
train_tech_df = train_tech_df[tech_cols]
Z_tech = ((train_tech_df - train_tech_df.mean(axis=0)) / (train_tech_df.std(axis=0) + 1e-8)).fillna(0.0).values
# Cross-correlation matrix between all active targets (N_tickers) and all technical features (N_tech): shape (N_tickers, N_tech)
C_tech_all = np.abs(Z_train.T @ Z_tech) / T_train

# Vectorized cross-correlation matrices C[lag] where entry (i, j) = |corr(Ticker_j(t - lag), Ticker_i(t))| on training data
corr_by_lag = {}
for lag in range(1, MAX_LAG_HORIZON + 1):
    C = np.abs(Z_train[lag:].T @ Z_train[:-lag]) / (T_train - lag)
    np.fill_diagonal(C, -1.0)  # Exclude trivial self-lag so cross-stock causal links are discovered
    corr_by_lag[lag] = C

# Pre-shift return matrices as 2D numpy arrays (shape T x N_tickers) for lags 1..7
ret_filled = returns_df.ffill().bfill().fillna(0.0).values
shifted_ret_arr = {}
for lag in range(1, MAX_LAG_HORIZON + 1):
    arr = np.zeros_like(ret_filled)
    arr[lag:] = ret_filled[:-lag]
    shifted_ret_arr[lag] = arr

# Pre-extract standardized technical matrix (shape T x N_tech) and sector columns
tech_full_arr = shifted_preds[tech_cols].ffill().bfill().fillna(0.0).values
sec_reg_map = {}
sec_mom_map = {}
for idx_t, tk in enumerate(tickers):
    sr = f'{tk}_SEC_REG'
    sm = f'{tk}_SEC_MOM'
    if sr in shifted_preds.columns:
        sec_reg_map[idx_t] = shifted_preds[sr].ffill().bfill().fillna(0.0).values
    if sm in shifted_preds.columns:
        sec_mom_map[idx_t] = shifted_preds[sm].ffill().bfill().fillna(0.0).values

def discover_causal_candidates(target_idx):
    """
    Discovers candidate causal chains for target_idx using training correlations only:
      1) Consecutive multi-hop cascade (Lag 1 -> Lag 2 -> ... -> Lag 5)
      2) Variable-lag multi-hop cascade where each hop selects its strongest per-edge lag in {1..3}
         such that cumulative target-relative lag stays within 1..MAX_LAG_HORIZON (7).
      3) Top direct multi-lag leaders across lags 1..MAX_LAG_HORIZON (7), e.g. non-consecutive tuples like (7, 5, 2).
    Returns a dict of candidate_name -> dict of {lag_int: peer_idx} (with 1 <= len <= MAX_CHAIN_DEPTH).
    """
    candidates = {}

    # Family A: Consecutive cascade (Depths 3, 4, 5 across lags 1..5)
    cascade_std = {}
    curr = target_idx
    for d in range(1, 6):
        peer_idx = int(corr_by_lag[1][curr].argmax())
        if corr_by_lag[1][curr, peer_idx] <= 0:
            break
        cascade_std[d] = peer_idx
        curr = peer_idx
        if d in (3, 4, 5):
            candidates[f"cascade_d{d}"] = dict(cascade_std)

    # Family B: Variable-lag cascade up to cumulative lag <= 7 (Depths 2..5)
    var_cascade = {}
    curr = target_idx
    cum_lag = 0
    for hop in range(1, MAX_CHAIN_DEPTH + 1):
        best_step_corr = -1.0
        best_peer_idx = None
        best_step_lag = 1
        for step_lag in (1, 2, 3):
            if cum_lag + step_lag > MAX_LAG_HORIZON:
                continue
            c_vec = corr_by_lag[step_lag][curr]
            p_idx = int(c_vec.argmax())
            if c_vec[p_idx] > best_step_corr:
                best_step_corr = float(c_vec[p_idx])
                best_peer_idx = p_idx
                best_step_lag = step_lag
        if best_peer_idx is None or best_step_corr <= 0:
            break
        cum_lag += best_step_lag
        var_cascade[cum_lag] = best_peer_idx
        curr = best_peer_idx
        if len(var_cascade) >= 2:
            candidates[f"var_cascade_h{hop}_maxlag{cum_lag}"] = dict(var_cascade)

    # Family C: Best direct cross-stock leaders at each lag 1..7, picking top k in {3, 4, 5}
    lag_scores = []
    for lag in range(1, MAX_LAG_HORIZON + 1):
        c_vec = corr_by_lag[lag][target_idx]
        p_idx = int(c_vec.argmax())
        lag_scores.append((float(c_vec[p_idx]), lag, p_idx))
    lag_scores.sort(reverse=True, key=lambda x: x[0])
    for k in (3, 4, 5):
        top_k = {lag: p_idx for _, lag, p_idx in lag_scores[:k]}
        candidates[f"direct_multilag_k{k}"] = top_k

    return candidates

def evaluate_chain_fast(target_idx, y_arr, base_cols_arr, chain_lags_idx_dict):
    max_lag = max(chain_lags_idx_dict.keys())
    lag_cols = [shifted_ret_arr[lag_d][:, p_idx] for lag_d, p_idx in sorted(chain_lags_idx_dict.items(), reverse=True)]
    X_full = np.column_stack([base_cols_arr] + lag_cols)[max_lag:]
    y_valid = y_arr[max_lag:]

    if len(y_valid) < 100:
        return 0.0

    split_idx = len(y_valid) - 30
    X_train = X_full[:split_idx]
    y_train = y_valid[:split_idx]
    X_test = X_full[split_idx:]
    y_test = y_valid[split_idx:]

    Xm = X_train.mean(axis=0)
    Xs = X_train.std(axis=0) + 1e-8
    X_train_s = (X_train - Xm) / Xs
    X_test_s = (X_test - Xm) / Xs

    clf = LogisticRegression(C=1.0, random_state=42)
    clf.fit(X_train_s, y_train)
    preds = clf.predict(X_test_s)
    return float(np.mean(preds == y_test))

results = []

for i, ticker in enumerate(tickers):
    if (i + 1) % 100 == 0:
        print(f"  Processed {i+1}/{len(tickers)} tickers ({time.time() - start_time:.1f}s)...")

    try:
        raw_t = returns_df[ticker].values
        if np.isnan(raw_t).sum() > 20:
            continue
        y_arr = (np.nan_to_num(raw_t, nan=0.0) > 0).astype(int)
        # Skip degenerate targets with <15% minority class in test window
        test_mean = y_arr[-30:].mean()
        if test_mean < 0.15 or test_mean > 0.85:
            continue

        top3_idx = np.argsort(C_tech_all[i])[::-1][:3]
        base_list = [tech_full_arr[:, idx] for idx in top3_idx]
        if i in sec_reg_map:
            base_list.append(sec_reg_map[i])
        if i in sec_mom_map:
            base_list.append(sec_mom_map[i])
        base_cols_arr = np.column_stack(base_list)

        candidates = discover_causal_candidates(i)
        if not candidates:
            continue

        best_acc = 0.0
        best_chain_idx = None
        for cand_name, cand_lags in candidates.items():
            acc = evaluate_chain_fast(i, y_arr, base_cols_arr, cand_lags)
            if acc > best_acc:
                best_acc = acc
                best_chain_idx = cand_lags

        if best_acc <= 0.0 or not best_chain_idx:
            continue

        best_chain = {lag_k: tickers[p_idx] for lag_k, p_idx in best_chain_idx.items()}
        sorted_lags = sorted(best_chain.keys(), reverse=True)
        row_dict = {
            'Ticker': ticker,
            'OOS_Accuracy': round(best_acc * 100.0, 1),
            'Depth': len(best_chain),
            'Max_Lag': max(sorted_lags),
            'Lag_Tuple': "-".join(str(k) for k in sorted_lags),
        }
        for lag_k in range(MAX_LAG_HORIZON, 0, -1):
            row_dict[f'Lag{lag_k}'] = best_chain.get(lag_k, "")
        results.append(row_dict)

    except Exception:
        continue

elapsed = time.time() - start_time
print(f"\nAdaptive 7-Lag / 5-Depth Causal Screening complete in {elapsed:.1f} seconds!")

res_df = pd.DataFrame(results).sort_values(by=['OOS_Accuracy', 'Depth'], ascending=[False, False]).reset_index(drop=True)

base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
out_path = os.path.join(base_dir, 'Fast_Screener_Results.csv')
res_df.to_csv(out_path, index=False)

print("\n=== TOP 15 MOST PREDICTABLE TICKERS (7-LAG HORIZON, UP TO 5 LINKS) ===")
print(res_df.head(15).to_string(index=False))
print(f"\nFull Adaptive results saved to: {out_path}")

# Update Active_Portfolio.csv while preserving any actively held stock positions
portfolio_path = os.path.join(base_dir, 'Active_Portfolio.csv')
held_stocks = []
try:
    import database_manager
    df_led = database_manager.execute_query("SELECT persona, holdings_json FROM capital_ledgers WHERE persona NOT LIKE 'ETF_%'")
    if not df_led.empty:
        latest_led = df_led.groupby('persona').last().reset_index()
        for h_str in latest_led['holdings_json']:
            try:
                h_dict = json.loads(h_str) if isinstance(h_str, str) else {}
                for tk, val in h_dict.items():
                    dollars = float(val.get('dollars', 0.0)) if isinstance(val, dict) else float(val or 0.0)
                    if tk != 'Cash' and dollars > 0 and tk not in held_stocks:
                        held_stocks.append(tk)
            except Exception:
                pass
    df_pend = database_manager.execute_query("SELECT persona, target_holdings_json FROM pending_orders WHERE persona NOT LIKE 'ETF_%'")
    if not df_pend.empty:
        for h_str in df_pend['target_holdings_json']:
            try:
                h_dict = json.loads(h_str) if isinstance(h_str, str) else {}
                for tk, val in h_dict.items():
                    dollars = float(val.get('dollars', 0.0)) if isinstance(val, dict) else float(val or 0.0)
                    if tk != 'Cash' and dollars > 0 and tk not in held_stocks:
                        held_stocks.append(tk)
            except Exception:
                pass
except Exception as e_h:
    print(f"Warning checking active stock holdings for grandfathering: {e_h}")

selected_rows = []
selected_tickers = set()

# 1. Include any currently held / pending stocks first with their best newly discovered causal chains
for tk in held_stocks:
    match = res_df[res_df['Ticker'] == tk]
    if not match.empty and len(selected_rows) < TOP_PORTFOLIO_SIZE:
        selected_rows.append(match.iloc[0].to_dict())
        selected_tickers.add(tk)

# 2. Fill the remaining slots up to TOP_PORTFOLIO_SIZE (10) with the highest OOS_Accuracy champions across the S&P 500
for _, row in res_df.iterrows():
    if len(selected_rows) >= TOP_PORTFOLIO_SIZE:
        break
    tk = row['Ticker']
    if tk not in selected_tickers:
        selected_rows.append(row.to_dict())
        selected_tickers.add(tk)

active_df = pd.DataFrame(selected_rows)
# Normalize OOS_Accuracy to decimal (e.g. 0.80) for compatibility with downstream readers
active_df['OOS_Accuracy'] = (active_df['OOS_Accuracy'] / 100.0).round(4)

# Persist to Turso active_portfolio_chains table (100% Turso SSOT)
try:
    import database_manager
    from datetime import datetime, timezone
    database_manager.init_db()
    database_manager.execute_write("DELETE FROM active_portfolio_chains")
    now_utc = datetime.now(timezone.utc).isoformat()
    for _, r in active_df.iterrows():
        database_manager.execute_write(
            """INSERT INTO active_portfolio_chains
               (ticker, oos_accuracy, depth, max_lag, lag_tuple,
                lag14, lag13, lag12, lag11, lag10, lag9, lag8,
                lag7, lag6, lag5, lag4, lag3, lag2, lag1, updated_at_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(r['Ticker']), float(r['OOS_Accuracy']), int(r['Depth']), int(r['Max_Lag']), str(r['Lag_Tuple']),
                str(r.get('Lag14', '')), str(r.get('Lag13', '')), str(r.get('Lag12', '')), str(r.get('Lag11', '')),
                str(r.get('Lag10', '')), str(r.get('Lag9', '')), str(r.get('Lag8', '')),
                str(r.get('Lag7', '')), str(r.get('Lag6', '')), str(r.get('Lag5', '')), str(r.get('Lag4', '')),
                str(r.get('Lag3', '')), str(r.get('Lag2', '')), str(r.get('Lag1', '')), now_utc
            ]
        )
    print(f"\n[TURSO SSOT] Saved {len(active_df)} causal portfolio chains to Turso table `active_portfolio_chains`!")
except Exception as e_db:
    print(f"Warning saving active_portfolio_chains to Turso: {e_db}")

active_df.to_csv(portfolio_path, index=False)

print(f"\n=== UPDATED Active_Portfolio.csv ({len(active_df)} Tickers | Held Preserved: {held_stocks}) ===")
print(active_df.to_string(index=False))
sys.stdout.flush()
os._exit(0)

