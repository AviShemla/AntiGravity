import pandas as pd
import numpy as np
import pymc as pm
import os
import sys
import subprocess

sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors

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
        
        # --- VOLUME CONFIRMATION PRIOR LOGIC ---
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
        # ---------------------------------------
            
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
    
    test_data = pd.concat([test_data, future_data])
    
    X_train = train_data[feat_cols].values
    y_train = train_data['Target_DIR'].values
    y_mag_train = train_data['Raw_Return_%'].values
    X_test = test_data[feat_cols].values
    y_test = test_data['Target_DIR'].values
    raw_return_test = test_data['Raw_Return_%'].values
    
    Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
    X_train_s = (X_train - Xm) / Xs
    X_test_s = (X_test - Xm) / Xs
    
    with pm.Model() as blr_model:
        X_data = pm.Data("X", X_train_s)
        
        # Direction Head
        alpha_dir = pm.Normal("alpha_dir", mu=fundamental_score, sigma=1)
        beta_dir = pm.Normal("beta_dir", mu=0, sigma=0.5, shape=X_train_s.shape[1])
        mu_dir = alpha_dir + pm.math.dot(X_data, beta_dir)
        p = pm.Deterministic("p", pm.math.sigmoid(mu_dir))
        pm.Bernoulli("y_obs_dir", p=p, observed=y_train, shape=X_data.shape[0])
        
        # Magnitude Head
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
    
    y_pred_class = (p_pred > 0.5).astype(float)
    
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
            
    # Fetch VIX for Override Notes
    vix_triggered = False
    try:
        import yfinance as yf
        vix_hist = yf.Ticker('^VIX').history(period='5d')
        if not vix_hist.empty and vix_hist['Close'].iloc[-1] > 30.0:
            vix_triggered = True
    except:
        pass

    # Calculate Kelly and Override
    kelly_allocs = []
    override_notes = []
    for p, mag, std, rec in zip(p_pred, mag_pred_mean, mag_pred_std, recs):
        if p > 0.65 and mag > 0:
            kelly = p - ((1 - p) / (mag / std))
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
            
    predicted_dir = ["UP" if p > 0.5 else "Down" for p in p_pred]
    actual_dir = []
    for y in y_test:
        if np.isnan(y): actual_dir.append("Pending")
        elif y == 1: actual_dir.append("UP")
        else: actual_dir.append("Down")
    
    # Dynamically build output columns based on depth
    sc_dict = {}
    for d in range(depth, 0, -1):
        dates_lag = dates_t - pd.Timedelta(days=d)
        sc_dict[f'date (lag{d})'] = dates_lag.date
        
    sc_dict['date'] = dates_t.date
    sc_dict['Bayesian Probability P(UP)'] = p_pred
    sc_dict['Expected Return %'] = mag_pred_mean / 100.0
    sc_dict['Expected Risk (Volatility) %'] = mag_pred_std / 100.0
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
    print("Loading data for Adaptive Bayesian Scorecard Export...")
    all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
    
    last_date = return_pivot.index.max()
    next_biz_day = last_date + pd.offsets.BDay(1)
    return_pivot.loc[next_biz_day] = np.nan
    all_predictors_df.loc[next_biz_day] = np.nan
    
    shifted_preds = all_predictors_df.shift(1)

    portfolio_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Active_Portfolio.csv'
    screener_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Fast_Screener_Results.csv'
    excel_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Top5_Bayesian_Scorecard_Formatted.xlsx'

    top_5 = pd.read_csv(portfolio_path)
    start_date = pd.to_datetime('2025-05-01')
    
    returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= next_biz_day)]

    scorecards = {}
    feat_cols_dict = {}
    failed_tickers = []
    retrained_tickers = []
    suspended_tickers = []

    fund_path = r'C:\Users\AviShemla\AntiGravity\financial_data\SP500_Fundamentals_Score.csv'
    fund_df = pd.DataFrame()
    if os.path.exists(fund_path):
        fund_df = pd.read_csv(fund_path)

    for idx, row in top_5.iterrows():
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
        if is_invalid:
            print(f"!!! [HEALTH CHECK FAILED] {ticker} has a broken/missing causal chain! Forcing retrain.")
            sc = pd.DataFrame(columns=[f'date (lag{d})' for d in range(depth, 0, -1)] + ['date', 'Bayesian Probability P(UP)', 'Expected Return %', 'Expected Risk (Volatility) %', 'actual value daily return %', 'model predicted direction daily return', 'actual Direction daily return', 'recommendation based on integrated model\n(e.g. "Buy", "Sell", "Hold")', 'model hit IND integrated model', 'Causality Link Used', 'Retraining_Status'])
            feat_cols = []
            last_hit = "Miss"
        else:
            print(f"  Applied Fundamental Prior Score: {fund_score}")
            sc, feat_cols, last_hit = evaluate_ticker(ticker, lags_dict, returns_df, shifted_preds, start_date, next_biz_day, fundamental_score=fund_score)
        
        sc['Retraining_Status'] = "" 
        scorecards[ticker] = sc
        feat_cols_dict[ticker] = feat_cols
        
        if last_hit == "Miss" and not is_invalid:
            print(f"!!! [HEALTH CHECK FAILED] {ticker} suffered a High-Confidence MISS yesterday! It requires retraining.")
            failed_tickers.append(ticker)
        elif is_invalid:
            failed_tickers.append(ticker)

    if failed_tickers:
        print(f"\n[RETRAINING PROTOCOL INITIATED] Retraining required for: {failed_tickers}")
        print("Running Adaptive fast_screener.py to discover best chains (This will take a few minutes)...")
        subprocess.run([sys.executable, "fast_screener.py"], cwd=r"C:\Users\AviShemla\AntiGravity")
        
        new_screener = pd.read_csv(screener_path)
        
        for ticker in failed_tickers:
            new_row = new_screener[new_screener['Ticker'] == ticker]
            if new_row.empty:
                print(f"!!! [CRITICAL FAILURE] Failed to find new chain for {ticker}. Trading Suspended.")
                # Ensure the dummy dataframe has at least one row for the Excel sheet
                if sc.empty:
                    sc.loc[0] = [np.nan] * len(sc.columns)
                sc['recommendation based on integrated model\n(e.g. "Buy", "Sell", "Hold")'] = "Hold (SUSPENDED)"
                sc['Retraining_Status'] = "SUSPENDED: No valid chain found"
                scorecards[ticker] = sc
                suspended_tickers.append(ticker)
                continue
                
            new_row = new_row.iloc[0]
            depth = int(new_row['Depth'])
            
            # Patch portfolio
            top_5.loc[top_5['Ticker'] == ticker, 'Depth'] = depth
            for d in range(5, 0, -1):
                col = f'Lag{d}'
                if d <= depth:
                    top_5.loc[top_5['Ticker'] == ticker, col] = new_row[col]
                else:
                    top_5.loc[top_5['Ticker'] == ticker, col] = np.nan
                    
            lags_dict = {d: new_row[f'Lag{d}'] for d in range(depth, 0, -1)}
            
            chain_str = " -> ".join([str(lags_dict[d]) for d in range(depth, 0, -1)])
            print(f"\nRe-evaluating {ticker} with NEW {depth}-Lag chain: {chain_str}")
            
            sc, feat_cols, _ = evaluate_ticker(ticker, lags_dict, returns_df, shifted_preds, start_date, next_biz_day, fundamental_score=fund_score)
            
            sc['Retraining_Status'] = f"Retrained dynamically to {depth}-Lag model"
            scorecards[ticker] = sc
            feat_cols_dict[ticker] = feat_cols
            retrained_tickers.append(f"{ticker} ({chain_str})")

        top_5.to_csv(portfolio_path, index=False)
        print("\nUpdated Active_Portfolio.csv with adaptive causal chains!")

    print("\nWriting formatted Excel Scorecard...")
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
    retrain_format = workbook.add_format({'bg_color': '#ffcccc', 'font_color': '#cc0000', 'bold': True})

    for ticker in top_5['Ticker']:
        sc = scorecards[ticker]
        feat_cols = feat_cols_dict[ticker]
        sheet_name = ticker
        
        sc.to_excel(writer, sheet_name=sheet_name, startrow=2, index=False)
        worksheet = writer.sheets[sheet_name]
        
        worksheet.merge_range('A1:M1', f'Ticker Predicted: {ticker}', meta_format)
        worksheet.merge_range('A2:E2', 'Model chosen: PyMC Dual-Head Bayesian (Logistic + Linear)', meta_format_light)
        worksheet.merge_range('F2:M2', f'Predictors: {", ".join(feat_cols)}', meta_format_light)
        
        for col_num, value in enumerate(sc.columns.values):
            worksheet.write(2, col_num, value, header_format)
            
        depth = len([c for c in sc.columns if 'date (lag' in c])
        # Dynamically set column widths
        worksheet.set_column(0, depth, 12, date_format) # All date columns
        base_col = depth + 1
        worksheet.set_column(base_col, base_col, 25) # Prob
        worksheet.set_column(base_col+1, base_col+2, 25, percent_format) # Exp Ret & Risk
        worksheet.set_column(base_col+3, base_col+3, 25, percent_format) # Actual return
        worksheet.set_column(base_col+4, base_col+5, 20) # Directions
        worksheet.set_column(base_col+6, base_col+6, 35) # Rec
        worksheet.set_column(base_col+7, base_col+7, 25, percent_format) # Kelly
        worksheet.set_column(base_col+8, base_col+8, 35) # Override Note
        worksheet.set_column(base_col+9, base_col+9, 25) # Hit
        worksheet.set_column(base_col+10, base_col+10, 60) # Causality Link
        worksheet.set_column(base_col+11, base_col+11, 45) # Retrain Status
        
        last_row = len(sc) + 3
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"On target"', 'format': green_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Miss"', 'format': red_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Pending"', 'format': neutral_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Hold"', 'format': neutral_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Buy"', 'format': green_format})
        worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Sell"', 'format': red_format})
        
        # Color retraining column
        # In this dynamic layout, Retraining_Status is the last column
        status_col_letter = chr(ord('A') + base_col + 11)
        if ord(status_col_letter) <= ord('Z'):
            worksheet.conditional_format(f'{status_col_letter}4:{status_col_letter}{last_row}', {'type': 'cell', 'criteria': '!=', 'value': '""', 'format': retrain_format})

    writer.close()
    print(f"\nSaved Formatted Scorecard to: {excel_path}")
    
    if retrained_tickers:
        print("\n=== RETRAINED TICKERS SUMMARY ===")
        print(", ".join(retrained_tickers))
    else:
        print("\n=== RETRAINED TICKERS SUMMARY ===")
        print("None")

    if suspended_tickers:
        print("\n=== SUSPENDED TICKERS SUMMARY ===")
        print(", ".join(suspended_tickers))
    else:
        print("\n=== SUSPENDED TICKERS SUMMARY ===")
        print("None")
