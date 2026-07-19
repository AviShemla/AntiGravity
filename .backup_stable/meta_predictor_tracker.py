import pandas as pd
import numpy as np
import json
import os
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
DATA_PATH = os.path.join(BASE_DIR, 'SP500_Clean_Advanced_Analysis.csv')
PRIORS_OUT_PATH = os.path.join(BASE_DIR, 'Meta_Alpha_Priors.json')

# We use an Expanding Window approach starting exactly 1 year ago.
# As time goes on, this window expands indefinitely to accumulate knowledge.
START_DATE = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime('%Y-%m-%d')

def build_meta_tracker():
    print(f"--- Meta-Predictor Alpha Tracking System ---")
    print(f"Loading Global S&P 500 Dataset from {DATA_PATH}...")
    
    try:
        df = pd.read_csv(DATA_PATH, low_memory=False)
    except FileNotFoundError:
        print(f"Dataset not found at {DATA_PATH}")
        return
        
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Apply Expanding Window Constraint
    df = df[df['Date'] >= START_DATE].copy()
    print(f"Accumulating knowledge from {START_DATE} to {df['Date'].max().date()} ({len(df):,} rows)...")
    
    # Build Target Direction (Next day's return)
    df = df.sort_values(['Ticker', 'Date'])
    df['Target_DIR'] = (df.groupby('Ticker')['Daily_Return_%'].shift(-1) > 0).astype(int)
    
    # Map Categoricals exactly like data_loader.py
    if 'Analyst_Consensus' in df.columns:
        ac_map = {'Strong Buy': 2, 'Buy': 1, 'Hold': 0, 'Sell': -1, 'Strong Sell': -2}
        df['Analyst_Consensus_Num'] = df['Analyst_Consensus'].map(ac_map).fillna(0)
    
    fear_col = 'Market_Fear_Level' if 'Market_Fear_Level' in df.columns else 'Market_Fear_Level_x'
    if fear_col in df.columns:
        df['Market_Fear_Num'] = df[fear_col].map({'Complacency / Calm': 0, 'High Volatility': 1}).fillna(0)
        
    if 'Sector_Regime' in df.columns:
        df['Sector_Regime_Num'] = df['Sector_Regime'].map({'BULL_REGIME': 1, 'BEAR_REGIME': -1}).fillna(0)
        
    df['RAS_Signal_Num'] = df['RAS_Signal'].map({'BUY': 1, 'HOLD': 0, 'SELL': -1}).fillna(0) if 'RAS_Signal' in df.columns else 0
    
    # Define Base Features
    base_features = {
        '_RSI': 'RSI_14d',
        '_ADX': 'ADX_14d',
        '_PLUS_DI': 'Plus_DI_14d',
        '_MINUS_DI': 'Minus_DI_14d',
        '_ATR': 'ATR_14d',
        '_RAS': 'RAS_Signal_Num'
    }
    
    if 'Analyst_Consensus_Num' in df.columns:
        base_features['_AC'] = 'Analyst_Consensus_Num'
    if 'Analyst_Upside_%' in df.columns:
        base_features['_UPSIDE'] = 'Analyst_Upside_%'
    if 'Sector_Regime_Num' in df.columns:
        base_features['_SEC_REG'] = 'Sector_Regime_Num'
    if 'Sector_Momentum_Score' in df.columns:
        base_features['_SEC_MOM'] = 'Sector_Momentum_Score'
    if 'Market_Fear_Num' in df.columns:
        base_features['_VIX'] = 'Market_Fear_Num'
        
    print(f"Evaluating {len(base_features)} Alpha Predictors...")
    
    # Fill missing values for the features to prevent dropna from deleting all historical data
    for feat_col in base_features.values():
        if feat_col in df.columns:
            df[feat_col] = df[feat_col].fillna(0)
    
    # Drop rows where target is missing (last day of each ticker)
    train_df = df.dropna(subset=['Target_DIR']).copy()
    
    X = train_df[list(base_features.values())].values
    y = train_df['Target_DIR'].values
    
    # Standardize Features (Because PyMC standardizes features, our Alpha scores must be scaled equivalently)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # We use a Logistic Regression with C=1.0 (L2 Regularization) to extract the Beta coefficients.
    # This perfectly mirrors the PyMC Normal(mu=0, sigma=1) prior structure.
    print("Training Global Logistic Regression Model on Expanding Window...")
    lr = LogisticRegression(solver='lbfgs', max_iter=1000)
    lr.fit(X_scaled, y)
    
    # Extract coefficients
    meta_priors = {}
    print("\n--- Empirical Alpha Scores (Hyper-Priors) ---")
    for i, (suffix, col_name) in enumerate(base_features.items()):
        coef = round(float(lr.coef_[0][i]), 4)
        meta_priors[suffix] = coef
        # Add a visual indicator
        trend = "[POSITIVE ALPHA]" if coef > 0.05 else "[NEGATIVE ALPHA]" if coef < -0.05 else "[NEUTRAL NOISE]"
        print(f" {suffix.ljust(12)} : {str(coef).ljust(7)} -> {trend}")
        
    with open(PRIORS_OUT_PATH, 'w') as f:
        json.dump(meta_priors, f, indent=4)
        
    print(f"\nSUCCESS: Global Meta-Priors saved to {PRIORS_OUT_PATH}")

if __name__ == '__main__':
    build_meta_tracker()
