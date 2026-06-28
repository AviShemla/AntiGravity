import pandas as pd
import numpy as np
import pymc as pm
import os
import sys
import subprocess
import gc

sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors
from failover_downloader import is_quarantined, log_warning

def make_quarantined_scorecard(ticker, depth, returns_df, next_biz_day, reason="API Data Failure"):
    dates_t = returns_df.index
    sc_dict = {}
    for d in range(depth, 0, -1):
        dates_lag = dates_t - pd.Timedelta(days=d)
        sc_dict[f'date (lag{d})'] = dates_lag.date
        
    sc_dict['date'] = dates_t.date
    sc_dict['SV Engine Used'] = [False] * len(dates_t)
    sc_dict['Bayesian Probability P(UP)'] = [0.5] * len(dates_t)
    sc_dict['Expected Return %'] = [0.0] * len(dates_t)
    sc_dict['Expected Risk (Volatility) %'] = [0.0] * len(dates_t)
    sc_dict['actual value daily return %'] = [np.nan] * len(dates_t)
    sc_dict['model predicted direction daily return'] = ["Down"] * len(dates_t)
    sc_dict['actual Direction daily return'] = ["Pending"] * len(dates_t)
    sc_dict['recommendation based on integrated model\n(e.g. "Buy", "Sell", "Hold")'] = ["Hold (QUARANTINED)"] * len(dates_t)
    sc_dict['Kelly Optimal Allocation %'] = [0.0] * len(dates_t)
    sc_dict['Broker Override Note'] = [f"QUARANTINED: {reason}"] * len(dates_t)
    sc_dict['model hit IND integrated model'] = ["Pending"] * len(dates_t)
    sc_dict['Causality Link Used'] = ["None"] * len(dates_t)
    
    return pd.DataFrame(sc_dict)

os.environ["PYTENSOR_FLAGS"] = "cxx="

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
        
    ac_name = f'{ticker}_AC'
    if ac_name in shifted_preds.columns:
        components.append(shifted_preds[ac_name].rename(f'{ac_name}_t-1'))
        feat_cols.append(f'{ac_name}_t-1')
        
    upside_name = f'{ticker}_UPSIDE'
    if upside_name in shifted_preds.columns:
        components.append(shifted_preds[upside_name].rename(f'{upside_name}_t-1'))
        feat_cols.append(f'{upside_name}_t-1')
        
    data_with_future = pd.concat(components, axis=1).loc[start_date:next_biz_day]
    # Forward fill any missing predictors (e.g. if Friday's data was NaN from yfinance)
    data_with_future[feat_cols] = data_with_future[feat_cols].ffill()
    data_with_future = data_with_future.dropna(subset=feat_cols)
    
    historical_data = data_with_future.dropna(subset=['Target_DIR'])
    
    if next_biz_day not in data_with_future.index:
        raise ValueError(f"Missing complete feature data for next_biz_day ({next_biz_day}) after ffill.")
        
    future_data = data_with_future.loc[[next_biz_day]]
    
    split_idx = len(historical_data) - 30
    train_data = historical_data.iloc[:split_idx]
    test_data = historical_data.iloc[split_idx:]
    
    test_data = pd.concat([test_data, future_data])
    
    X_train = train_data[feat_cols].values
    y_train = train_data['Target_DIR'].values.astype(np.int32)
    y_mag_train = train_data['Raw_Return_%'].values
    X_test = test_data[feat_cols].values
    y_test = test_data['Target_DIR'].values.astype(np.int32)
    raw_return_test = test_data['Raw_Return_%'].values
    
    Xm = X_train.mean(0); Xs = X_train.std(0)
    Xs[Xs < 1e-5] = 1.0  # Cap zero std to prevent normalization explosion
    X_train_s = (X_train - Xm) / Xs
    X_test_s = (X_test - Xm) / Xs
    
    # ==========================================
    # V2 STOCHASTIC VOLATILITY ENGINE (RUST)
    # ==========================================
    sv_engine_used = False
    sv_vol_test = None
    is_held = False
    
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
        
        sv_vol_test = sv_vol_shifted[-len(test_data):]
        sv_engine_used = True
        print("  => SV Engine SUCCESS.")
        
        # Aggressive garbage collection to prevent RAM leaks in the loop
        del sv_model, trace_sv
        gc.collect()
        
    except Exception as e:
        print(f"  => SV Engine FAILED: {e}. Falling back to standard posterior stddev.")
        sv_engine_used = False
        sv_vol_test = np.zeros(len(test_data)) # Dummy array
        
        try:
            import glob
            import json
            ledger_files = glob.glob(r'C:\Users\AviShemla\AntiGravity\financial_data\Capital_Ledger_*.csv')
            for lf in ledger_files:
                df_l = pd.read_csv(lf)
                if not df_l.empty and 'Holdings_JSON' in df_l.columns:
                    holdings_str = df_l.iloc[-1]['Holdings_JSON']
                    holdings = json.loads(holdings_str)
                    if ticker in holdings and holdings[ticker] > 0:
                        is_held = True
                        break
        except Exception as ex:
            print(f"  Error checking stock holdings: {ex}")
            
        if is_held:
            log_warning(f"🚨 {ticker} model degraded to V1 standard deviation (Rust SV Engine failed). Positions frozen to HOLD.")
        else:
            log_warning(f"⚠️ {ticker} model degraded to V1 standard deviation (Rust SV Engine failed). Standard Kelly risk sizing active.")
    # ==========================================
    
    with pm.Model() as blr_model:
        X_data = pm.Data("X", X_train_s)
        
        # --- Inject Meta-Tracker Hyper-Priors ---
        import json
        try:
            prior_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Meta_Alpha_Priors.json'
            with open(prior_path, 'r') as f:
                meta_priors = json.load(f)
        except Exception as e:
            print(f"  => Meta-Priors not found or error ({e}). Defaulting to 0.")
            meta_priors = {}
            
        mu_beta_list = []
        for feat in feat_cols:
            # Map specific feature suffix (e.g. AAPL_RSI -> _RSI) to get its alpha score
            matched = False
            for suffix, alpha_score in meta_priors.items():
                if feat.endswith(suffix):
                    mu_beta_list.append(alpha_score)
                    matched = True
                    break
            if not matched:
                mu_beta_list.append(0.0) # Default if not found
                
        mu_beta_array = np.array(mu_beta_list, dtype=np.float64)
        
        alpha_dir = pm.Normal("alpha_dir", mu=fundamental_score, sigma=1)
        # Using the empirical Hyper-Priors as the mu constraint instead of 0
        beta_dir = pm.Normal("beta_dir", mu=mu_beta_array, sigma=0.5, shape=X_train_s.shape[1])
        mu_dir = alpha_dir + pm.math.dot(X_data, beta_dir)
        p = pm.Deterministic("p", pm.math.sigmoid(mu_dir))
        pm.Bernoulli("y_obs_dir", p=p, observed=y_train, shape=X_data.shape[0])
        
        alpha_mag = pm.Normal("alpha_mag", mu=0, sigma=2)
        beta_mag = pm.Normal("beta_mag", mu=0, sigma=1, shape=X_train_s.shape[1])
        mu_mag = alpha_mag + pm.math.dot(X_data, beta_mag)
        sigma_mag = pm.HalfNormal("sigma_mag", sigma=3)
        pm.Normal("y_obs_mag", mu=mu_mag, sigma=sigma_mag, observed=y_mag_train, shape=X_data.shape[0])
        
        trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
        pm.set_data({"X": X_test_s})
        pp = pm.sample_posterior_predictive(trace, var_names=["p", "y_obs_mag"], progressbar=False)
        
    p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
    mag_pred_mean = pp.posterior_predictive["y_obs_mag"].mean(dim=["chain", "draw"]).values
    mag_pred_std = pp.posterior_predictive["y_obs_mag"].std(dim=["chain", "draw"]).values
    
    dates_t = test_data.index
    
    force_hold = (not sv_engine_used) and is_held

    def get_recommendation(p):
        if force_hold:
            return "Hold"
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
        
        if p > 0.65 and mag > 0 and not force_hold:
            kelly = p - ((1 - p) / ( (mag / 100.0) / active_risk ))
            kelly = max(0.0, min(1.0, kelly))
            kelly_allocs.append(kelly)
        else:
            kelly_allocs.append(0.0)
            
        note = ""
        if force_hold:
            note = "HOLD: V1 Fallback (Held Position Frozen)"
        elif rec == "Buy":
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
    print("Loading data for V2 Stochastic Volatility Test...")
    all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
    
    last_date = return_pivot.index.max()
    next_biz_day = last_date + pd.offsets.BDay(1)
    return_pivot.loc[next_biz_day] = np.nan
    all_predictors_df.loc[next_biz_day] = np.nan
    
    shifted_preds = all_predictors_df.shift(1)

    portfolio_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Active_Portfolio.csv'
    excel_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Top5_Bayesian_Scorecard_Formatted.xlsx'

    top_5 = pd.read_csv(portfolio_path)
    
    # PHASE 1 TEST: Limit to ONLY 10 stocks!
    top_10 = top_5
    
    start_date = pd.to_datetime('2025-05-01')
    returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= next_biz_day)]

    scorecards = {}
    feat_cols_dict = {}

    fund_path = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Fundamentals_Score.csv'
    fund_df = pd.DataFrame()
    if os.path.exists(fund_path):
        fund_df = pd.read_csv(fund_path)

    for i, (idx, row) in enumerate(top_10.iterrows()):
        if i > 0 and i % 10 == 0:
            print(f"\n--- PAUSING 10 SECONDS TO COOL DOWN CPU & FLUSH RAM (Processed {i} tickers) ---")
            import time
            time.sleep(10)
            import gc
            gc.collect()
            
        ticker = row['Ticker']
        depth = int(row.get('Depth', 3))
        
        fund_score = 0.0
        if not fund_df.empty and ticker in fund_df['Ticker'].values:
            fund_score = float(fund_df[fund_df['Ticker'] == ticker]['Fundamental_Score'].iloc[0])
            
        lags_dict = {}
        is_invalid = False
        for d in range(depth, 0, -1):
            val = row[f'Lag{d}']
            if pd.isna(val) or val == "":
                is_invalid = True
            lags_dict[d] = val
            
        print(f"\nProcessing {ticker} (Adaptive Depth: {depth})...")
        if is_quarantined(ticker):
            print(f"[QUARANTINE TRIGGERED] {ticker} is quarantined due to data errors. Building dummy scorecard.")
            sc = make_quarantined_scorecard(ticker, depth, returns_df, next_biz_day, "API Data Failure")
            scorecards[ticker] = sc
            feat_cols_dict[ticker] = []
            continue
            
        if is_invalid:
            print(f"!!! {ticker} has broken chain. Skipping in SV Sandbox.")
            continue
        
        try:
            sc, feat_cols, last_hit = evaluate_ticker(ticker, lags_dict, returns_df, shifted_preds, start_date, next_biz_day, fundamental_score=fund_score)
            scorecards[ticker] = sc
            feat_cols_dict[ticker] = feat_cols
        except Exception as e:
            print(f"!!! Error evaluating {ticker} for scorecard: {e}")
            log_warning(f"🚨 Model crash for {ticker}: {e}. Forcing quarantine and HOLD.")
            sc = make_quarantined_scorecard(ticker, depth, returns_df, next_biz_day, f"Model Crash: {e}")
            scorecards[ticker] = sc
            feat_cols_dict[ticker] = []

    print("\nWriting formatted Test Excel Scorecard...")
    writer = pd.ExcelWriter(excel_path, engine='xlsxwriter')
    workbook = writer.book

    header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1})
    meta_format = workbook.add_format({'bold': True, 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1})
    meta_format_light = workbook.add_format({'bold': True, 'fg_color': '#8ea9db', 'font_color': 'white', 'text_wrap': True, 'border': 1})
    green_format = workbook.add_format({'bg_color': '#e2efda', 'font_color': '#375623'})
    red_format = workbook.add_format({'bg_color': '#fce4d6', 'font_color': '#c00000'})
    neutral_format = workbook.add_format({'bg_color': '#fff2cc', 'font_color': '#806000'})
    date_format = workbook.add_format({'num_format': 'dd/mm/yyyy'})
    percent_format = workbook.add_format({'num_format': '0.00%'})

    for ticker in scorecards:
        sc = scorecards[ticker]
        feat_cols = feat_cols_dict[ticker]
        sheet_name = ticker
        
        sc.to_excel(writer, sheet_name=sheet_name, startrow=2, index=False)
        worksheet = writer.sheets[sheet_name]
        
        worksheet.merge_range('A1:N1', f'Ticker Predicted: {ticker}', meta_format)
        worksheet.merge_range('A2:F2', 'Model chosen: PyMC Dual-Head + Rust SV Engine', meta_format_light)
        worksheet.merge_range('G2:N2', f'Predictors: {", ".join(feat_cols)}', meta_format_light)
        
        for col_num, value in enumerate(sc.columns.values):
            worksheet.write(2, col_num, value, header_format)
            
        depth = len([c for c in sc.columns if 'date (lag' in c])
        worksheet.set_column(0, depth, 12, date_format) 
        base_col = depth + 1
        worksheet.set_column(base_col, base_col, 15) # SV Used
        worksheet.set_column(base_col+1, base_col+1, 25) # Prob
        worksheet.set_column(base_col+2, base_col+3, 25, percent_format) # Exp Ret & Risk
        worksheet.set_column(base_col+4, base_col+4, 25, percent_format) # Actual return
        worksheet.set_column(base_col+5, base_col+6, 20) # Directions
        worksheet.set_column(base_col+7, base_col+7, 35) # Rec
        worksheet.set_column(base_col+8, base_col+8, 25, percent_format) # Kelly
        worksheet.set_column(base_col+9, base_col+9, 35) # Override Note
        worksheet.set_column(base_col+10, base_col+10, 25) # Hit
        worksheet.set_column(base_col+11, base_col+11, 60) # Causality Link
        
        last_row = len(sc) + 3
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"On target"', 'format': green_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Miss"', 'format': red_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Pending"', 'format': neutral_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Hold"', 'format': neutral_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Buy"', 'format': green_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Sell"', 'format': red_format})

    writer.close()
    print(f"\nSaved Formatted Scorecard to: {excel_path}")
