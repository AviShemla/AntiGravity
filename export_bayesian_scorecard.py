import pandas as pd
import numpy as np
import pymc as pm
import os
import sys

sys.path.insert(0, r'C:\Users\AviShemla\AntiGravity')
from data_loader import load_predictors

os.environ["PYTENSOR_FLAGS"] = "cxx="

print("Loading data for Excel Export...")
all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot = load_predictors()
shifted_preds = all_predictors_df.shift(1)

screener_df = pd.read_csv(r'C:\Users\AviShemla\AntiGravity\financial_data\Fast_Screener_Results.csv')
top_5 = screener_df.head(5)

start_date = pd.to_datetime('2025-05-01')
end_date = return_pivot.index.max()
returns_df = return_pivot.loc[(return_pivot.index >= start_date) & (return_pivot.index <= end_date)]

excel_path = r'C:\Users\AviShemla\AntiGravity\financial_data\Top5_Bayesian_Scorecard.xlsx'

with pd.ExcelWriter(excel_path) as writer:
    for idx, row in top_5.iterrows():
        ticker = row['Ticker']
        yyy = row['Lag3']
        zzz = row['Lag2']
        xxx = row['Lag1']
        
        print(f"Processing {ticker}...")
        
        target_t = returns_df[ticker].rename('Target_t')
        
        comb = pd.concat([target_t, shifted_preds], axis=1).loc[start_date:end_date].dropna(how='all', axis=1).dropna(subset=['Target_t'])
        corrs = comb.drop('Target_t', axis=1).corrwith(comb['Target_t'])
        tech_corrs = corrs[~corrs.index.str.contains('SEC_REG|SEC_MOM|VIX|Market_Fear', case=False, na=False)]
        top_3_tech = tech_corrs.abs().sort_values(ascending=False).head(3).index.tolist()
        
        chain_3 = returns_df[yyy].shift(3).rename(f'{yyy}_Lag3')
        chain_2 = returns_df[zzz].shift(2).rename(f'{zzz}_Lag2')
        chain_1 = returns_df[xxx].shift(1).rename(f'{xxx}_Lag1')
        
        feat_cols = top_3_tech + [chain_3.name, chain_2.name, chain_1.name]
        
        components = [
            (target_t > 0).astype(int).rename('Target_DIR'),
            target_t.rename('Raw_Return_%'),
            shifted_preds[top_3_tech],
            chain_3, chain_2, chain_1
        ]
        
        sec_reg_name = f'{ticker}_SEC_REG'
        sec_mom_name = f'{ticker}_SEC_MOM'
        
        if sec_reg_name in shifted_preds.columns:
            components.append(shifted_preds[sec_reg_name].rename(f'{sec_reg_name}_t-1'))
            feat_cols.append(f'{sec_reg_name}_t-1')
        if sec_mom_name in shifted_preds.columns:
            components.append(shifted_preds[sec_mom_name].rename(f'{sec_mom_name}_t-1'))
            feat_cols.append(f'{sec_mom_name}_t-1')
            
        data = pd.concat(components, axis=1).loc[start_date:end_date].dropna()
        
        split_idx = len(data) - 30
        train_data = data.iloc[:split_idx]
        test_data = data.iloc[split_idx:]
        
        X_train = train_data[feat_cols].values
        y_train = train_data['Target_DIR'].values
        X_test = test_data[feat_cols].values
        y_test = test_data['Target_DIR'].values
        raw_return_test = test_data['Raw_Return_%'].values
        
        Xm = X_train.mean(0); Xs = X_train.std(0) + 1e-8
        X_train_s = (X_train - Xm) / Xs
        X_test_s = (X_test - Xm) / Xs
        
        try:
            print(f"DEBUG {ticker}: X_train_s shape={X_train_s.shape}, dtype={X_train_s.dtype}")
            print(f"DEBUG {ticker}: y_train shape={y_train.shape}, dtype={y_train.dtype}")
            with pm.Model() as blr_model:
                X_data = pm.Data("X", X_train_s)
                y_data = pm.Data("y", y_train)
                alpha = pm.Normal("alpha", mu=0, sigma=1)
                beta = pm.Normal("beta", mu=0, sigma=0.5, shape=X_train_s.shape[1])
                mu = alpha + pm.math.dot(X_data, beta)
                p = pm.Deterministic("p", pm.math.sigmoid(mu))
                pm.Bernoulli("y_obs", p=p, observed=y_data, shape=X_data.shape[0])
                
                trace = pm.sample(draws=1000, tune=1000, chains=2, target_accept=0.9, random_seed=42, progressbar=False)
                
                import numpy as np
                pm.set_data({"X": X_test_s, "y": np.zeros(len(X_test_s), dtype=int)})
                pp = pm.sample_posterior_predictive(trace, var_names=["p"], progressbar=False)
                
            p_pred = pp.posterior_predictive["p"].mean(dim=["chain", "draw"]).values
            y_pred_class = (p_pred > 0.5).astype(int)
            
            sc = pd.DataFrame({
                'Date': test_data.index.date,
                'Ticker': ticker,
                'Raw_Return_%': raw_return_test,
                'Bayesian_Prob_UP': p_pred,
                'Actual_Direction': np.where(y_test == 1, 'UP', 'DOWN'),
                'Predicted_Direction': np.where(y_pred_class == 1, 'UP', 'DOWN'),
                'Hit_Miss': np.where(y_test == y_pred_class, 'HIT', 'MISS'),
                'Is_High_Confidence': np.where((p_pred > 0.65) | (p_pred < 0.35), 'YES', 'NO')
            })
            
        except Exception as e:
            print(f"!!! CRASH processing {ticker}: {e}")
            BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
            with open(os.path.join(BASE_DIR, 'pipeline_warnings.txt'), 'a') as f:
                f.write(f"🚨 MODEL CRASH for {ticker} in PyMC: {e}. Auto-Quarantining to protect portfolio.\n")
            
            import numpy as np
            dates_t = test_data.index.date
            sc = pd.DataFrame({
                'Date': dates_t,
                'Ticker': ticker,
                'Raw_Return_%': np.zeros(len(dates_t)),
                'Bayesian_Prob_UP': np.full(len(dates_t), 0.5),
                'Actual_Direction': ['Pending'] * len(dates_t),
                'Predicted_Direction': ['DOWN'] * len(dates_t),
                'Hit_Miss': ['MISS'] * len(dates_t),
                'Is_High_Confidence': ['NO'] * len(dates_t)
            })

        # Save to a sheet named after the ticker
        sc.to_excel(writer, sheet_name=ticker, index=False)

print(f"\nSaved Scorecard to: {excel_path}")
