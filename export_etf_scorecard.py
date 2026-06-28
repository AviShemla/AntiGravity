import pandas as pd
import numpy as np
import pymc as pm
import os
import sys
import gc
import warnings
from timeout_runner import run_with_timeout

def run_sv_engine(returns_full):
    import pymc as pm
    import numpy as np
    import os
    
    # Force PyTensor to avoid recompiling C headers inside multiprocessing workers
    os.environ["PYTENSOR_FLAGS"] = "cxx="
    
    with pm.Model() as sv_model:
        step_size = pm.Exponential('step_size', 10)
        volatility = pm.GaussianRandomWalk('volatility', sigma=step_size, shape=len(returns_full))
        nu = pm.Exponential('nu', 0.1)
        returns_obs = pm.StudentT('returns_obs', nu=nu, lam=pm.math.exp(-2 * volatility), observed=returns_full)
        trace_sv = pm.sample(draws=500, tune=500, chains=1, cores=1, progressbar=False, nuts_sampler="nutpie")
        
    return np.exp(trace_sv.posterior['volatility'].mean(dim=['chain', 'draw']).values)

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
os.environ["PYTENSOR_FLAGS"] = "cxx="

def write_etf_excel(target_etf, sc, features):
    out_excel = os.path.join(BASE_DIR, f'{target_etf}_Bayesian_Scorecard.xlsx')
    writer = pd.ExcelWriter(out_excel, engine='xlsxwriter')
    workbook = writer.book
    
    # [DAY 1 BASELINE ENFORCEMENT] Strip all 30-day historical context prior to Day 1
    day1_epoch = pd.to_datetime('2026-06-22').date()
    sc['date_ts'] = pd.to_datetime(sc['Date']).dt.date
    sc = sc[sc['date_ts'] >= day1_epoch].copy()
    sc = sc.drop(columns=['date_ts'])
    
    sc.to_excel(writer, sheet_name=target_etf, startrow=2, index=False)
    worksheet = writer.sheets[target_etf]
    
    meta_format = workbook.add_format({'bold': True, 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1})
    header_format = workbook.add_format({'bold': True, 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1, 'text_wrap': True})
    pct_format = workbook.add_format({'num_format': '0.00%'})
    
    worksheet.merge_range('A1:L1', f'Target ETF: {target_etf} | Hybrid Causal Model', meta_format)
    worksheet.merge_range('A2:L2', f'Optimal Features Discovered: {", ".join(features)}', meta_format)
    
    for col_num, value in enumerate(sc.columns.values):
        worksheet.write(2, col_num, value, header_format)
        
    worksheet.set_column(0, 0, 15)
    worksheet.set_column(1, 1, 15) # SV Used
    worksheet.set_column(2, 5, 18, pct_format)
    worksheet.set_column(7, 9, 18)
    worksheet.set_column(11, 11, 35) # Override Note
    
    green_format = workbook.add_format({'bg_color': '#e2efda', 'font_color': '#375623'})
    red_format = workbook.add_format({'bg_color': '#fce4d6', 'font_color': '#c00000'})
    neutral_format = workbook.add_format({'bg_color': '#fff2cc', 'font_color': '#806000'})
    hit_format = workbook.add_format({'bg_color': '#33CC33', 'font_color': '#000000', 'bold': True})  
    miss_format = workbook.add_format({'bg_color': '#FF0000', 'font_color': '#FFFFFF', 'bold': True}) 
    
    last_row = len(sc) + 3
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"UP"', 'format': green_format})
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Down"', 'format': red_format})
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Pending"', 'format': neutral_format})
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Hold"', 'format': neutral_format})
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Buy"', 'format': green_format})
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Sell"', 'format': red_format})
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"On target"', 'format': hit_format})
    worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Miss"', 'format': miss_format})
    
    writer.close()
    print(f"\nSUCCESS: Generated Scorecard -> {out_excel}")

def export_etf_scorecard(target_etf, target_date=None):
    print(f"\n--- Generating Bayesian ETF Scorecard for {target_etf} ---")
    
    from failover_downloader import is_quarantined, log_warning
    
    is_quar = is_quarantined(target_etf)
    matrix_path = os.path.join(BASE_DIR, f'{target_etf}_Hybrid_Matrix.csv')
    screener_path = os.path.join(BASE_DIR, f'{target_etf}_Hybrid_Screener_Results.csv')
    
    if is_quar or not os.path.exists(matrix_path) or not os.path.exists(screener_path):
        print(f"[QUARANTINE TRIGGERED] {target_etf} is quarantined or data files are missing. Building dummy scorecard.")
        dates_t = pd.bdate_range(end=pd.Timestamp.now(), periods=31)
        n = len(dates_t)
        
        # Try to preserve history
        old_sc_path = os.path.join(BASE_DIR, 'financial_data', f'{target_etf}_Bayesian_Scorecard.xlsx')
        sc = None
        if os.path.exists(old_sc_path):
            try:
                old_df = pd.read_excel(old_sc_path)
                if len(old_df) >= n - 1:
                    old_df = old_df.tail(n - 1).copy()
                    
                    new_row = old_df.iloc[-1].copy()
                    new_row['Date'] = dates_t[-1].strftime('%Y-%m-%d')
                    new_row['Actual Daily Return %'] = np.nan
                    new_row['Predicted Direction'] = "Down"
                    new_row['Actual Direction'] = "Pending"
                    new_row['Recommendation'] = "Hold"
                    new_row['Kelly Optimal Allocation %'] = 0.0
                    new_row['Broker Override Note'] = "QUARANTINED: API Data Failure"
                    new_row['Model Hit'] = "Pending"
                    new_row['Retraining_Status'] = "QUARANTINED"
                    
                    sc = pd.concat([old_df, pd.DataFrame([new_row])], ignore_index=True)
            except Exception as e:
                pass
                
        if sc is None:
            # Fallback if no history exists
            sc_dict = {
                'Date': dates_t.strftime('%Y-%m-%d'),
                'SV Engine Used': [False] * n,
                'Bayesian Probability P(UP)': [0.5] * n,
                'Expected Return %': [0.0] * n,
                'Expected Risk (Volatility) %': [0.01] * n,
                'Kelly Optimal Allocation %': [0.0] * n,
                'Actual Daily Return %': [np.nan] * n,
                'Predicted Direction': ["Down"] * n,
                'Actual Direction': ["Pending"] * n,
                'Recommendation': ["Hold"] * n,
                'Model Hit': ["Pending"] * n,
                'Broker Override Note': ["QUARANTINED: API Data Failure"] * n
            }
            sc = pd.DataFrame(sc_dict)
            sc['Retraining_Status'] = "QUARANTINED"
        write_etf_excel(target_etf, sc, ["None"])
        return
        
    best_chain = pd.read_csv(screener_path).iloc[0]
    features = [best_chain['Macro_1'], best_chain['Macro_2'], best_chain['Micro_1'], best_chain['Micro_2']]
    print(f"Best Features: {features}")
    
    df = pd.read_csv(matrix_path, index_col=0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if target_date:
        target_ts = pd.to_datetime(target_date)
        df = df.loc[df.index <= target_ts]
    else:
        target_ts = df.index.max()
        
    import pandas_market_calendars as mcal
    nyse = mcal.get_calendar('NYSE')
    schedule = nyse.schedule(start_date=target_ts.strftime('%Y-%m-%d'), end_date=(target_ts + pd.Timedelta(days=7)).strftime('%Y-%m-%d'))
    next_biz_day = schedule.iloc[1].name.tz_localize(None) if len(schedule) > 1 else target_ts + pd.Timedelta(days=1)
    
    if target_ts not in df.index:
        df.loc[target_ts] = np.nan
    df.loc[next_biz_day] = np.nan
    
    dir_col = f'{target_etf}_Direction'
    ret_col = f'{target_etf}_Return_%'
    
    df['Target_DIR'] = df[dir_col].shift(-1)
    df['Target_RET'] = df[ret_col].shift(-1)
    
    import yfinance as yf
    for feat in features:
        if feat not in df.columns:
            print(f"[WARNING] Feature {feat} missing from matrix. Initializing with 0.0 to prevent crash.")
            df[feat] = 0.0
            
        if '_Lag' in feat:
            ticker, lag_str = feat.split('_Lag')
            try:
                lag = int(lag_str)
                hist = yf.Ticker(ticker).history(period='1y')
                if 'Volume' in hist.columns and not hist.empty:
                    vol = hist['Volume']
                    vol_ma = vol.rolling(window=30, min_periods=1).mean()
                    vol_ratio = vol / vol_ma
                    
                    if vol_ratio.index.tz is not None:
                        vol_ratio.index = vol_ratio.index.tz_localize(None)
                        
                    vol_ratio_aligned = vol_ratio.reindex(df.index).fillna(1.0)
                    vol_ratio_shifted = vol_ratio_aligned.shift(lag)
                    
                    df[feat] = df[feat] * vol_ratio_shifted
            except:
                pass
                
    df[features] = df[features].ffill()
    df[['Target_DIR', 'Target_RET']] = df[['Target_DIR', 'Target_RET']].ffill()
    data = df.dropna(subset=features)
    
    future_data = data.iloc[[-1]]
    historical_data = data.iloc[:-1].dropna(subset=['Target_DIR', 'Target_RET'])
    
    split_idx = len(historical_data) - 30
    train_data = historical_data.iloc[:split_idx]
    test_data = historical_data.iloc[split_idx:]
    
    test_data = pd.concat([test_data, future_data])
    
    X_train = train_data[features].values
    y_train = train_data['Target_DIR'].values
    y_mag_train = train_data['Target_RET'].values
    
    X_test = test_data[features].values
    y_test = test_data['Target_DIR'].values
    raw_return_test = test_data['Target_RET'].values
    
    Xm = X_train.mean(axis=0)
    Xs = X_train.std(axis=0)
    Xs[Xs < 1e-5] = 1.0  
    X_train_s = (X_train - Xm) / Xs
    X_test_s = (X_test - Xm) / Xs
    
    # ==========================================
    # V2 STOCHASTIC VOLATILITY ENGINE (RUST)
    # ==========================================
    sv_engine_used = False
    sv_vol_test = None
    
    # Check if target ETF is currently held
    is_held = False
    try:
        import glob
        import json
        ledger_files = glob.glob(os.path.join(BASE_DIR, 'ETF_Capital_Ledger_*.csv'))
        for lf in ledger_files:
            df_l = pd.read_csv(lf)
            if not df_l.empty and 'Holdings_JSON' in df_l.columns:
                holdings_str = df_l.iloc[-1]['Holdings_JSON']
                holdings = json.loads(holdings_str)
                if target_etf in holdings and holdings[target_etf] > 0:
                    is_held = True
                    break
    except Exception as ex:
        print(f"  Error checking ETF holdings: {ex}")

    try:
        print("  => Running Rust-Compiled SV Engine (with 10-minute freeze timeout)...")
        returns_full = data['Target_RET'].fillna(0.0).values / 100.0
        
        inferred_volatility = run_with_timeout(run_sv_engine, args=(returns_full,), timeout_seconds=600)
        
        sv_vol_shifted = np.roll(inferred_volatility, 1)
        sv_vol_shifted[0] = inferred_volatility[0]
        
        sv_vol_test = sv_vol_shifted[split_idx:]
        sv_engine_used = True
        print("  => SV Engine SUCCESS.")
        
        gc.collect()
        
    except Exception as e:
        print(f"  => SV Engine FAILED: {e}. Falling back to 14-day stddev.")
        sv_engine_used = False
        sv_vol_test = np.zeros(len(test_data))
        
        if is_held:
            log_warning(f"🚨 {target_etf} model degraded to V1 standard deviation (Rust SV Engine failed). Positions frozen to HOLD.")
        else:
            log_warning(f"⚠️ {target_etf} model degraded to V1 standard deviation (Rust SV Engine failed). Standard Kelly risk sizing active.")
    # ==========================================
    
    print("  => Sampling Dual-Head Bayesian Model (This takes ~30 seconds)...")
    
    whale_scores_list = []
    whale_weights_list = []
    etf_agg_score = 0.0
    
    try:
        from etf_whale_extractor import get_60_percent_whales_with_weights
        whales_dict = get_60_percent_whales_with_weights(target_etf)
        fund_path = os.path.join(BASE_DIR, 'SP500_Fundamentals_Score.csv')
        if os.path.exists(fund_path) and whales_dict:
            fund_df = pd.read_csv(fund_path).set_index('Ticker')
            for whale, weight in whales_dict.items():
                if whale in fund_df.index:
                    score = fund_df.loc[whale, 'Fundamental_Score']
                    if isinstance(score, pd.Series):
                        score = score.iloc[0]
                    if pd.notna(score):
                        whale_scores_list.append(float(score))
                        whale_weights_list.append(float(weight))
            
            if len(whale_weights_list) > 0:
                total_w = sum(whale_weights_list)
                whale_weights_list = [w / total_w for w in whale_weights_list]
                etf_agg_score = sum(s * w for s, w in zip(whale_scores_list, whale_weights_list))
    except Exception as e:
        print(f"  [ETF PRIOR] Failed to load whale priors: {e}")
        
    whale_scores = np.array(whale_scores_list) if whale_scores_list else np.array([0.0])
    whale_weights = np.array(whale_weights_list) if whale_weights_list else np.array([1.0])
    
    try:  # PyMC Dual-Head Bayesian Sampling
        with pm.Model() as model:
            X_data = pm.Data("X", X_train_s)
            y_data_dir = pm.Data("y_dir", y_train)
            y_data_mag = pm.Data("y_mag", y_mag_train)
            
            alpha_dir = pm.Normal("alpha_dir", mu=0, sigma=1)
            beta_dir = pm.Normal("beta_dir", mu=0, sigma=0.5, shape=X_train_s.shape[1])
            
            if etf_agg_score != 0.0:
                whale_prior = pm.Normal("whale_prior", mu=etf_agg_score, sigma=0.5)
                mu_dir = alpha_dir + pm.math.dot(X_data, beta_dir) + whale_prior
            else:
                mu_dir = alpha_dir + pm.math.dot(X_data, beta_dir)
                
            p = pm.Deterministic("p", pm.math.sigmoid(mu_dir))
            pm.Bernoulli("y_obs_dir", p=p, observed=y_data_dir)
            
            alpha_mag = pm.Normal("alpha_mag", mu=0, sigma=2)
            beta_mag = pm.Normal("beta_mag", mu=0, sigma=1, shape=X_train_s.shape[1])
            mu_mag = alpha_mag + pm.math.dot(X_data, beta_mag)
            sigma_mag = pm.HalfNormal("sigma_mag", sigma=3)
            pm.Normal("y_obs_mag", mu=mu_mag, sigma=sigma_mag, observed=y_data_mag)
            
            trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
            
            pm.set_data({
                "X": X_test_s, 
                "y_dir": np.zeros(len(X_test_s), dtype=int),
                "y_mag": np.zeros(len(X_test_s))
            })
            pp = pm.sample_posterior_predictive(trace, var_names=["p", "y_obs_mag"], progressbar=False)
            
        p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
        mag_pred_mean = pp.posterior_predictive["y_obs_mag"].mean(dim=["chain", "draw"]).values
        y_pred_class = (p_pred > 0.5).astype(int)
        
        sc = pd.DataFrame({
            'Date': test_data.index.date,
            'Ticker': target_etf,
            'Actual Daily Return %': raw_return_test,
            'Expected Risk (Volatility) %': sv_vol_test,
            'Bayesian Probability P(UP)': p_pred,
            'Expected Return %': mag_pred_mean,
            'Actual_Direction': np.where(y_test == 1, 'UP', 'DOWN'),
            'Predicted_Direction': np.where(y_pred_class == 1, 'UP', 'DOWN'),
            'Hit_Miss': np.where(y_test == y_pred_class, 'HIT', 'MISS'),
            'Retraining_Status': ['Stable'] * len(test_data)
        })
        
    except Exception as e:
        print(f"!!! CRASH processing {target_etf}: {e}")
        with open(os.path.join(BASE_DIR, 'pipeline_warnings.txt'), 'a', encoding='utf-8') as f:
            f.write(f"🚨 MODEL CRASH for {target_etf} in PyMC ETF Engine: {e}. Auto-Quarantining to protect portfolio.\n")
        
        dates_t = test_data.index.date
        sc = pd.DataFrame({
            'Date': dates_t,
            'Ticker': target_etf,
            'Actual Daily Return %': np.zeros(len(dates_t)),
            'Expected Risk (Volatility) %': np.zeros(len(dates_t)),
            'Bayesian Probability P(UP)': np.full(len(dates_t), 0.5),
            'Expected Return %': np.zeros(len(dates_t)),
            'Actual_Direction': ['Pending'] * len(dates_t),
            'Predicted_Direction': ['DOWN'] * len(dates_t),
            'Hit_Miss': ['MISS'] * len(dates_t),
            'Retraining_Status': ['QUARANTINED_PYMC_CRASH'] * len(dates_t)
        })

    print("  => Writing to Excel...")
    
    expected_vol_fallback = train_data['Target_RET'].tail(14).std() / 100.0
    if np.isnan(expected_vol_fallback) or expected_vol_fallback == 0:
        expected_vol_fallback = 0.01 
        
    force_hold = (not sv_engine_used) and is_held
    
    # --- INTEGRATED MODEL INJECTION ---
    shadow_csv = os.path.join(BASE_DIR, "Shadow_Transformer_Scorecard.csv")
    engine_used_str = "PyMC SV Engine (V1)"
    if os.path.exists(shadow_csv):
        try:
            shadow_df = pd.read_csv(shadow_csv)
            shadow_df['Date'] = pd.to_datetime(shadow_df['Date']).dt.strftime('%Y-%m-%d')
            target_dt_str = pd.to_datetime(target_date).strftime('%Y-%m-%d') if target_date else test_data.index[-1].strftime('%Y-%m-%d')
            match = shadow_df[(shadow_df['Ticker'] == target_etf) & (shadow_df['Date'] == target_dt_str)]
            if not match.empty:
                dl_prob = float(match['Transformer_P(UP)'].iloc[0])
                p_pred[-1] = dl_prob
                engine_used_str = "Deep Learning + SV Volatility (V2 Integrated)"
        except Exception as e:
            pass
            
    def get_recommendation(p):
        if force_hold:
            return "Hold"
        if p >= 0.51: return "Buy"
        elif p <= 0.49: return "Sell"
        else: return "Hold"
        
    recs = [get_recommendation(p) for p in p_pred]
    predicted_dir = ["UP" if p > 0.5 else "Down" for p in p_pred]
    actual_dir = ["UP" if y == 1 else "Down" if y == 0 else "Pending" for y in y_test]
    
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
    for i, (p, mag, rec) in enumerate(zip(p_pred, mag_pred_mean, recs)):
        active_risk = sv_vol_test[i] if sv_engine_used else expected_vol_fallback
        
        if p >= 0.51 and mag > 0 and not force_hold:
            R = 1.0
            if mag > 0:
                calculated_R = (mag / 100.0) / active_risk
                if calculated_R > 0.1:
                    R = calculated_R
            kelly = p - ((1 - p) / R)
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
            
    sc_dict = {
        'Date': test_data.index.strftime('%Y-%m-%d'),
        'SV Engine Used': [engine_used_str] * len(p_pred),
        'Bayesian Probability P(UP)': p_pred,
        'Expected Return %': mag_pred_mean / 100.0,
        'Expected Risk (Volatility) %': sv_vol_test if sv_engine_used else [expected_vol_fallback] * len(p_pred),
        'Kelly Optimal Allocation %': kelly_allocs,
        'Actual Daily Return %': raw_return_test / 100.0,
        'Predicted Direction': predicted_dir,
        'Actual Direction': actual_dir,
        'Recommendation': recs,
        'Model Hit': hits,
        'Broker Override Note': override_notes
    }
    
    sc = pd.DataFrame(sc_dict)
    sc['Retraining_Status'] = "Stable" if sv_engine_used else "V1_FALLBACK"
    
    write_etf_excel(target_etf, sc, features)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs='?', default='XLK')
    parser.add_argument("--target-date", type=str, help="Target date to simulate catch-up execution")
    args = parser.parse_args()
    export_etf_scorecard(args.target, target_date=args.target_date)
