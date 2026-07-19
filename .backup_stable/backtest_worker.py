import os
os.environ["PYTENSOR_FLAGS"] = "cxx=,optimizer=fast_compile"
import pandas as pd
import numpy as np
import pymc as pm
import sys
import subprocess
import gc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_predictors

def evaluate_ticker(ticker, lags_dict, returns_df, shifted_preds, start_date, next_biz_day, fundamental_score=0.0):
    target_t = returns_df[ticker].rename('Target_t')
    
    target_dir = (target_t > 0).astype(float)
    target_dir.loc[target_t.isna()] = np.nan
    target_dir = target_dir.rename('Target_DIR')
    
    comb = pd.concat([target_t, shifted_preds], axis=1).loc[start_date:next_biz_day].dropna(how='all', axis=1)
    hist_comb = comb.dropna(subset=['Target_t'])
    corrs = hist_comb.drop('Target_t', axis=1).corrwith(hist_comb['Target_t'])
    tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
    top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()
    
    feat_cols = top_3_tech.copy()
    components = [
        target_dir,
        target_t.rename('Raw_Return_%'),
        shifted_preds[top_3_tech]
    ]
    
    depth = len(lags_dict)
    chain_elements = []
    
    import yfinance as yf
    
    for d in range(depth, 0, -1):
        lag_name = lags_dict[d]
        raw_lag = returns_df[lag_name].shift(d)
        
        try:
            hist = yf.Ticker(lag_name).history(period='1y')
            if 'Volume' in hist.columns and not hist.empty:
                vol = hist['Volume']
                vol_ma = vol.rolling(window=30, min_periods=1).mean()
                vol_ratio = vol / vol_ma
                
                if vol_ratio.index.tz is not None:
                    vol_ratio.index = vol_ratio.index.tz_localize(None)
                    
                vol_ratio_aligned = vol_ratio.reindex(returns_df.index).fillna(1.0)
                vol_ratio_shifted = vol_ratio_aligned.shift(d)
                
                chain_col = (raw_lag * vol_ratio_shifted).rename(f'{lag_name}_Lag{d}')
            else:
                chain_col = raw_lag.rename(f'{lag_name}_Lag{d}')
        except:
            chain_col = raw_lag.rename(f'{lag_name}_Lag{d}')
            
        components.append(chain_col)
        feat_cols.append(chain_col.name)
        chain_elements.append(chain_col.name)
        
    actual_chain_str = " -> ".join(chain_elements) + f" -> {ticker}"
    
    sec_reg_name = f'{ticker}_SEC_REG'
    sec_mom_name = f'{ticker}_SEC_MOM'
    
    if sec_reg_name in shifted_preds.columns:
        components.append(shifted_preds[sec_reg_name].rename(f'{sec_reg_name}_t-1'))
        feat_cols.append(f'{sec_reg_name}_t-1')
    if sec_mom_name in shifted_preds.columns:
        components.append(shifted_preds[sec_mom_name].rename(f'{sec_mom_name}_t-1'))
        feat_cols.append(f'{sec_mom_name}_t-1')
        
    data_with_future = pd.concat(components, axis=1).loc[start_date:next_biz_day]
    data_with_future = data_with_future.dropna(subset=feat_cols)
    
    historical_data = data_with_future.dropna(subset=['Target_DIR'])
    future_data = data_with_future.loc[[next_biz_day]]
    
    split_idx = len(historical_data) - 30
    train_data = historical_data.iloc[:split_idx]
    test_data = historical_data.iloc[split_idx:]
    
    if next_biz_day not in test_data.index:
        test_data = pd.concat([test_data, future_data])
    else:
        # Prevent duplicate append in backtest when the target day already has returns data
        pass
    
    X_train = train_data[feat_cols].values
    y_train = train_data['Target_DIR'].values
    y_mag_train = train_data['Raw_Return_%'].values
    X_test = test_data[feat_cols].values
    y_test = test_data['Target_DIR'].values
    raw_return_test = test_data['Raw_Return_%'].values
    
    Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
    X_train_s = (X_train - Xm) / Xs
    X_test_s = (X_test - Xm) / Xs
    
    # ==========================================
    # V2 STOCHASTIC VOLATILITY ENGINE (RUST)
    # ==========================================
    sv_engine_used = False
    sv_vol_test = None
    
    try:
        print("  => Running Rust-Compiled SV Engine...")
        # Get full historical returns for SV
        returns_full = data_with_future['Raw_Return_%'].fillna(0.0).values / 100.0
        
        with pm.Model() as sv_model:
            step_size = pm.Exponential('step_size', 10)
            volatility = pm.GaussianRandomWalk('volatility', sigma=step_size, shape=len(returns_full))
            nu = pm.Exponential('nu', 0.1)
            returns_obs = pm.StudentT('returns_obs', nu=nu, lam=pm.math.exp(-2 * volatility), observed=returns_full)
            trace_sv = pm.sample(draws=500, tune=500, chains=1, cores=1, progressbar=False, nuts_sampler="nutpie")
            
        inferred_volatility = np.exp(trace_sv.posterior['volatility'].mean(dim=['chain', 'draw']).values)
        
        # Shift forward to prevent lookahead bias (tomorrow's risk is based on today's volatility)
        sv_vol_shifted = np.roll(inferred_volatility, 1)
        sv_vol_shifted[0] = inferred_volatility[0]
        
        sv_vol_test = sv_vol_shifted[split_idx:]
        sv_engine_used = True
        print("  => SV Engine SUCCESS.")
        
        # Aggressive garbage collection to prevent RAM leaks in the loop
        del sv_model, trace_sv
        gc.collect()
        
    except Exception as e:
        print(f"  => SV Engine FAILED: {e}. Falling back to standard posterior stddev.")
        sv_engine_used = False
        sv_vol_test = np.zeros(len(test_data)) # Dummy array
    # ==========================================
    
    with pm.Model() as blr_model:
        X_data = pm.Data("X", X_train_s)
        
        alpha_dir = pm.Normal("alpha_dir", mu=fundamental_score, sigma=1)
        beta_dir = pm.Normal("beta_dir", mu=0, sigma=0.5, shape=X_train_s.shape[1])
        mu_dir = alpha_dir + pm.math.dot(X_data, beta_dir)
        p = pm.Deterministic("p", pm.math.sigmoid(mu_dir))
        pm.Bernoulli("y_obs_dir", p=p, observed=y_train, shape=X_data.shape[0])
        
        alpha_mag = pm.Normal("alpha_mag", mu=0, sigma=2)
        beta_mag = pm.Normal("beta_mag", mu=0, sigma=1, shape=X_train_s.shape[1])
        mu_mag = alpha_mag + pm.math.dot(X_data, beta_mag)
        sigma_mag = pm.HalfNormal("sigma_mag", sigma=3)
        pm.Normal("y_obs_mag", mu=mu_mag, sigma=sigma_mag, observed=y_mag_train, shape=X_data.shape[0])
        
        trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, random_seed=42, progressbar=False, nuts_sampler="nutpie")
        pm.set_data({"X": X_test_s})
        pp = pm.sample_posterior_predictive(trace, var_names=["p", "y_obs_mag"], progressbar=False)
        
    p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
    mag_pred_mean = pp.posterior_predictive["y_obs_mag"].mean(dim=["chain", "draw"]).values
    mag_pred_std = pp.posterior_predictive["y_obs_mag"].std(dim=["chain", "draw"]).values
    
    dates_t = test_data.index
    
    def get_recommendation(p):
        if p > 0.65: return "Buy"
        elif p < 0.35: return "Sell"
        else: return "Hold"
        
    recs = [get_recommendation(p) for p in p_pred]
    
    hits = []
    for actual, rec in zip(y_test, recs):
        if np.isnan(actual):
            hits.append("Pending")
        elif rec == "Hold":
            hits.append("Hold")
        elif (rec == "Buy" and actual == 1) or (rec == "Sell" and actual == 0):
            hits.append("On target")
        else:
            hits.append("Miss")
            
    vix_triggered = False
    try:
        import yfinance as yf
        vix_hist = yf.Ticker('^VIX').history(period='5d')
        if not vix_hist.empty and vix_hist['Close'].iloc[-1] > 30.0:
            vix_triggered = True
    except:
        pass

    kelly_allocs = []
    override_notes = []
    
    # Kelly Criterion dynamically switching between SV Risk and Standard Risk
    for i, (p, mag, std, rec) in enumerate(zip(p_pred, mag_pred_mean, mag_pred_std, recs)):
        # Calculate Risk: V2 True Volatility if available, else V1 Standard Deviation
        active_risk = sv_vol_test[i] if sv_engine_used else (std / 100.0)
        
        if p > 0.65 and mag > 0:
            kelly = p - ((1 - p) / ( (mag / 100.0) / active_risk ))
            kelly = max(0.0, min(1.0, kelly))
            kelly_allocs.append(kelly)
        else:
            kelly_allocs.append(0.0)
            
        note = ""
        if rec == "Buy":
            if vix_triggered:
                note = "Vetoed: Market Panic (VIX > 30)"
            elif kelly_allocs[-1] == 0.0:
                note = f"Vetoed: Win Prob {p*100:.1f}%, but payout too small to justify risk (Kelly=0)"
        override_notes.append(note)
            
    predicted_dir = ["UP" if p > 0.5 else "Down" for p in p_pred]
    actual_dir = []
    for y in y_test:
        if np.isnan(y): actual_dir.append("Pending")
        elif y == 1: actual_dir.append("UP")
        else: actual_dir.append("Down")
    
    sc_dict = {}
    for d in range(depth, 0, -1):
        dates_lag = dates_t - pd.Timedelta(days=d)
        sc_dict[f'date (lag{d})'] = dates_lag.date
        
    sc_dict['date'] = dates_t.date
    sc_dict['SV Engine Used'] = [sv_engine_used] * len(dates_t)
    sc_dict['Bayesian Probability P(UP)'] = p_pred
    sc_dict['Expected Return %'] = mag_pred_mean / 100.0
    sc_dict['Expected Risk (Volatility) %'] = sv_vol_test if sv_engine_used else (mag_pred_std / 100.0)
    sc_dict['actual value daily return %'] = raw_return_test / 100.0
    sc_dict['model predicted direction daily return'] = predicted_dir
    sc_dict['actual Direction daily return'] = actual_dir
    sc_dict['recommendation based on integrated model\n(e.g. "Buy", "Sell", "Hold")'] = recs
    sc_dict['Kelly Optimal Allocation %'] = kelly_allocs
    sc_dict['Broker Override Note'] = override_notes
    sc_dict['model hit IND integrated model'] = hits
    sc_dict['Causality Link Used'] = [actual_chain_str] * len(dates_t)
    
    sc = pd.DataFrame(sc_dict)
    last_hit = hits[-2] if len(hits) >= 2 else "Pending"
    
    return sc, feat_cols, last_hit

if __name__ == '__main__':
    import argparse
    import json
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True, help='Target date to predict (YYYY-MM-DD)')
    parser.add_argument('--tickers', required=True, help='Comma separated list of tickers')
    parser.add_argument('--out', required=True, help='Output JSON file path')
    args = parser.parse_args()
    
    target_date = pd.to_datetime(args.date)
    tickers_list = [t.strip() for t in args.tickers.split(',')]
    
    print(f"Loading data up to {target_date.strftime('%Y-%m-%d')} for {len(tickers_list)} tickers...")
    all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
    
    # We are predicting 'target_date'. So we can only train on data BEFORE target_date.
    # The actual dataframe has data up to today. We slice it.
    return_pivot = return_pivot[return_pivot.index <= target_date]
    all_predictors_df = all_predictors_df[all_predictors_df.index <= target_date]
    
    next_biz_day = target_date
    if next_biz_day not in return_pivot.index:
        return_pivot.loc[next_biz_day] = np.nan
        all_predictors_df.loc[next_biz_day] = np.nan
        
    return_pivot = return_pivot.sort_index()
    all_predictors_df = all_predictors_df.sort_index()
    
    shifted_preds = all_predictors_df.shift(1)
    start_date = pd.to_datetime('2025-05-01')
    returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= next_biz_day)]

    scorecards = {}
    
    fund_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'SP500_Fundamentals_Score.csv')
    fund_df = pd.DataFrame()
    if os.path.exists(fund_path):
        fund_df = pd.read_csv(fund_path)

    for i, ticker in enumerate(tickers_list):
        if i > 0 and i % 10 == 0:
            print(f"--- PAUSING 5 SECONDS TO COOL DOWN CPU (Processed {i} tickers) ---")
            import time
            time.sleep(5)
            import gc
            gc.collect()
            
        depth = 3 # Hardcode depth for backtest speed
        
        fund_score = 0.0
        if not fund_df.empty and ticker in fund_df['Ticker'].values:
            fund_score = float(fund_df[fund_df['Ticker'] == ticker]['Fundamental_Score'].iloc[0])
            
        lags_dict = {}
        for d in range(depth, 0, -1):
            lags_dict[d] = 'GOOGL' # fallback to GOOGL for chain
            
        print(f"\nProcessing {ticker} (Target Date: {target_date.strftime('%Y-%m-%d')})...")
        try:
            sc, _, _ = evaluate_ticker(ticker, lags_dict, returns_df, shifted_preds, start_date, next_biz_day, fundamental_score=fund_score)
            
            # Extract only the last row (the prediction for target_date)
            pred_row = sc.iloc[-1]
            scorecards[ticker] = {
                'prob': float(pred_row['Bayesian Probability P(UP)']),
                'exp_ret': float(pred_row['Expected Return %']),
                'exp_vol': float(pred_row['Expected Risk (Volatility) %'])
            }
        except Exception as e:
            print(f"Failed to process {ticker}: {e}")

    # Save to JSON
    with open(args.out, 'w') as f:
        json.dump(scorecards, f)
        
    print(f"\nSaved predictions to {args.out}")
