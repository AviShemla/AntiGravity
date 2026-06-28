import pandas as pd
import numpy as np
import pymc as pm
import os

BASE_DIR = r'C:\Users\AviShemla\AntiGravity\financial_data'
os.environ["PYTENSOR_FLAGS"] = "cxx="

def export_etf_scorecard(target_etf='XLK'):
    print(f"--- Generating Bayesian ETF Scorecard for {target_etf} ---")
    
    # 1. Load the Best Hybrid Chain
    screener_path = os.path.join(BASE_DIR, f'{target_etf}_Hybrid_Screener_Results.csv')
    if not os.path.exists(screener_path):
        print("Screener results not found!")
        return
        
    best_chain = pd.read_csv(screener_path).iloc[0]
    features = [best_chain['Macro_1'], best_chain['Macro_2'], best_chain['Micro_1'], best_chain['Micro_2']]
    print(f"Best Features: {features}")
    
    # 2. Load the Hybrid Matrix
    matrix_path = os.path.join(BASE_DIR, f'{target_etf}_Hybrid_Matrix.csv')
    df = pd.read_csv(matrix_path, index_col=0)
    df.index = pd.to_datetime(df.index)
    
    # Inject Analyst Predictors if they exist in the matrix
    if f'{target_etf}_AC' in df.columns:
        df[f'{target_etf}_AC'] = df[f'{target_etf}_AC'].fillna(0)
        features.append(f'{target_etf}_AC')
        print(f"  + Added {target_etf}_AC to features")
    if f'{target_etf}_UPSIDE' in df.columns:
        df[f'{target_etf}_UPSIDE'] = df[f'{target_etf}_UPSIDE'].fillna(0)
        features.append(f'{target_etf}_UPSIDE')
        print(f"  + Added {target_etf}_UPSIDE to features")
    
    # Targets
    dir_col = f'{target_etf}_Direction'
    ret_col = f'{target_etf}_Return_%'
    
    # We will predict the NEXT day, so we shift the targets UP by 1 (or shift features DOWN)
    # The matrix already aligns today's return with yesterday's Lag1, but we want to simulate
    # predicting Tomorrow based on Today's known data.
    # To do this, we shift the target columns backward by 1 day relative to the features.
    
    df['Target_DIR'] = df[dir_col].shift(-1)
    df['Target_RET'] = df[ret_col].shift(-1)
    
    # --- VOLUME CONFIRMATION PRIOR LOGIC ---
    import yfinance as yf
    for feat in features:
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
                    print(f"  Applied Volume Confirmation Prior to {feat}")
            except:
                pass
    # ---------------------------------------
    
    # 3. Train/Test Split (Last 30 days)
    data = df.dropna(subset=features)
    
    # The absolute last row has NaN for Target_DIR/RET, this is our "Tomorrow" prediction row
    future_data = data.iloc[[-1]]
    historical_data = data.iloc[:-1].dropna(subset=['Target_DIR', 'Target_RET'])
    
    split_idx = len(historical_data) - 30
    train_data = historical_data.iloc[:split_idx]
    test_data = historical_data.iloc[split_idx:]
    
    test_data = pd.concat([test_data, future_data])
    
    X_train = train_data[features].values
    y_train = train_data['Target_DIR'].values.astype(np.int32)
    y_mag_train = train_data['Target_RET'].values
    
    X_test = test_data[features].values
    y_test = test_data['Target_DIR'].values.astype(np.int32)
    raw_return_test = test_data['Target_RET'].values
    
    # Scale
    Xm = X_train.mean(axis=0)
    Xs = X_train.std(axis=0) + 1e-8
    X_train_s = (X_train - Xm) / Xs
    X_test_s = (X_test - Xm) / Xs
    
    # 4. Dual-Head PyMC Model
    print("Sampling Dual-Head Bayesian Model (This takes ~30 seconds)...")
    
    # --- DYNAMIC ETF MICRO-WHALE PRIOR LOGIC ---
    whale_scores_list = []
    whale_weights_list = []
    etf_agg_score = 0.0 # Fallback
    
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
                # Normalize the weights so they sum to 1.0 within the extracted subset
                total_w = sum(whale_weights_list)
                whale_weights_list = [w / total_w for w in whale_weights_list]
                
                print(f"  [ETF PRIOR] Loaded {len(whale_scores_list)} Micro-Whales for Dynamic PyMC Weighting.")
                # Calculate fallback
                etf_agg_score = sum(s * w for s, w in zip(whale_scores_list, whale_weights_list))
    except Exception as e:
        print(f"  [ETF PRIOR] Failed to load whale priors: {e}")
        
    whale_scores = np.array(whale_scores_list) if whale_scores_list else np.array([0.0])
    whale_weights = np.array(whale_weights_list) if whale_weights_list else np.array([1.0])
    # -------------------------------------------
    
    with pm.Model() as model:
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
        for feat in features:
            matched = False
            for suffix, alpha_score in meta_priors.items():
                if feat.endswith(suffix):
                    mu_beta_list.append(alpha_score)
                    matched = True
                    break
            if not matched:
                mu_beta_list.append(0.0)
                
        mu_beta_array = np.array(mu_beta_list, dtype=np.float64)
        
        # Head 1: Direction (Bernoulli)
        if len(whale_scores_list) > 0:
            # Dynamic Learned Prior
            # Allow PyMC to assign a Beta coefficient to each whale's fundamental score, centered around its official ETF weight
            beta_whales = pm.Normal("beta_whales", mu=whale_weights, sigma=0.5, shape=len(whale_weights))
            dynamic_etf_score = pm.math.dot(beta_whales, whale_scores)
            alpha_dir = pm.Normal("alpha_dir", mu=dynamic_etf_score, sigma=1)
        else:
            alpha_dir = pm.Normal("alpha_dir", mu=etf_agg_score, sigma=1)
            
        # Using the empirical Hyper-Priors as the mu constraint instead of 0
        beta_dir = pm.Normal("beta_dir", mu=mu_beta_array, sigma=0.5, shape=X_train_s.shape[1])
        mu_dir = alpha_dir + pm.math.dot(X_data, beta_dir)
        p = pm.Deterministic("p", pm.math.sigmoid(mu_dir))
        pm.Bernoulli("y_obs_dir", p=p, observed=y_train, shape=X_data.shape[0])
        
        # Head 2: Magnitude (Normal)
        alpha_mag = pm.Normal("alpha_mag", mu=0, sigma=2)
        beta_mag = pm.Normal("beta_mag", mu=0, sigma=1, shape=X_train_s.shape[1])
        mu_mag = alpha_mag + pm.math.dot(X_data, beta_mag)
        sigma_mag = pm.HalfNormal("sigma_mag", sigma=3)
        pm.Normal("y_obs_mag", mu=mu_mag, sigma=sigma_mag, observed=y_mag_train, shape=X_data.shape[0])
        
        trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
        
        # Posterior Predictive for Test Set
        pm.set_data({"X": X_test_s})
        pp = pm.sample_posterior_predictive(trace, var_names=["p", "y_obs_mag"], progressbar=False)
        
    p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
    mag_pred_mean = pp.posterior_predictive["y_obs_mag"].mean(dim=["chain", "draw"]).values
    
    # Expected Volatility (Rolling 14-day std dev on training data)
    expected_vol = train_data['Target_RET'].tail(14).std()
    if np.isnan(expected_vol) or expected_vol == 0:
        expected_vol = 1.0 # fallback
        
    # 5. Format Output Data
    def get_recommendation(p):
        if p > 0.55: return "Buy"
        elif p < 0.45: return "Sell"
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
    
    # Fetch VIX for Override Notes
    vix_triggered = False
    try:
        import yfinance as yf
        vix_hist = yf.Ticker('^VIX').history(period='5d')
        if not vix_hist.empty and vix_hist['Close'].iloc[-1] > 30.0:
            vix_triggered = True
    except:
        pass

    # Fractional Kelly Formula
    kelly_allocs = []
    override_notes = []
    for p, mag, rec in zip(p_pred, mag_pred_mean, recs):
        if p > 0.55 and mag > 0:
            kelly = p - ((1 - p) / (mag / expected_vol))
            kelly = max(0.0, min(1.0, kelly))
            kelly_allocs.append(kelly)
        else:
            kelly_allocs.append(0.0)
            
        note = ""
        if rec == "Buy":
            if vix_triggered:
                note = "Vetoed: Market Panic (VIX > 30)"
            elif kelly_allocs[-1] == 0.0:
                note = "Vetoed: Poor Risk/Reward (Kelly=0)"
        override_notes.append(note)
            
    sc_dict = {
        'Date': test_data.index.strftime('%Y-%m-%d'),
        'Bayesian Probability P(UP)': p_pred,
        'Expected Return %': mag_pred_mean / 100.0,
        'Expected Risk (Volatility) %': [expected_vol / 100.0] * len(p_pred),
        'Kelly Optimal Allocation %': kelly_allocs,
        'Actual Daily Return %': raw_return_test / 100.0,
        'Predicted Direction': predicted_dir,
        'Actual Direction': actual_dir,
        'Recommendation': recs,
        'Model Hit': hits,
        'Broker Override Note': override_notes
    }
    
    sc = pd.DataFrame(sc_dict)
    
    # 6. Write Excel
    out_excel = os.path.join(BASE_DIR, f'{target_etf}_Bayesian_Scorecard.xlsx')
    writer = pd.ExcelWriter(out_excel, engine='xlsxwriter')
    workbook = writer.book
    
    sc.to_excel(writer, sheet_name=target_etf, startrow=2, index=False)
    worksheet = writer.sheets[target_etf]
    
    meta_format = workbook.add_format({'bold': True, 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1})
    header_format = workbook.add_format({'bold': True, 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1, 'text_wrap': True})
    pct_format = workbook.add_format({'num_format': '0.00%'})
    
    worksheet.merge_range('A1:J1', f'Target ETF: {target_etf} | Hybrid Causal Model', meta_format)
    worksheet.merge_range('A2:J2', f'Optimal Features Discovered: {", ".join(features)}', meta_format)
    
    for col_num, value in enumerate(sc.columns.values):
        worksheet.write(2, col_num, value, header_format)
        
    worksheet.set_column(0, 0, 15)
    worksheet.set_column(1, 4, 18, pct_format)
    worksheet.set_column(6, 8, 18)
    worksheet.set_column(10, 10, 35) # Override Note
    
    green_format = workbook.add_format({'bg_color': '#e2efda', 'font_color': '#375623'})
    red_format = workbook.add_format({'bg_color': '#fce4d6', 'font_color': '#c00000'})
    neutral_format = workbook.add_format({'bg_color': '#fff2cc', 'font_color': '#806000'})
    
    # Custom vivid colors for Model Hits
    hit_format = workbook.add_format({'bg_color': '#33CC33', 'font_color': '#000000', 'bold': True})  # Vibrant fluorescent-ish green
    miss_format = workbook.add_format({'bg_color': '#FF0000', 'font_color': '#FFFFFF', 'bold': True}) # Pure bright Red
    
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

if __name__ == '__main__':
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else 'XLK'
    export_etf_scorecard(target)
