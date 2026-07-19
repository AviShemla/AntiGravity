import os
# =============================================================================
# data_loader.py  — Shared data loading utility for all AntiGravity workflows
# Handles schema variations in SP500_Clean_Advanced_Analysis.csv automatically
# =============================================================================
import pandas as pd
import numpy as np

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'SP500_Clean_Advanced_Analysis.csv')


def _pick(df, candidates):
    """Return the first available column from a list of candidates."""
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"None of {candidates} found. Available: {df.columns.tolist()}")


def load_predictors(ticker=None):
    """
    Load SP500 data and build the full predictor matrix.
    Returns:
        all_predictors_df  — wide DataFrame (Date × features), forward-filled
        return_pivot       — raw Daily_Return_% pivot (Date × Ticker)
        std_adj_returns    — return/stdev pivot (Date × Ticker)
        df                 — raw long-form DataFrame
    """
    print("Reading data...")
    df = pd.read_csv(DATA_PATH, low_memory=False)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.drop_duplicates(subset=['Date', 'Ticker']).sort_values(['Ticker', 'Date'])
    print(f"  {len(df):,} rows | {df['Ticker'].nunique()} tickers | "
          f"{df['Date'].min().date()} to {df['Date'].max().date()}")

    # ---- Detect schema-varying columns ----
    stdev_col = _pick(df, ['Daily_STDEV', 'STDEV_5d', 'STDEV_10d', 'STDEV_20d'])
    vix_col   = _pick(df, ['VIX_Close',   'VIX_Close_x'])
    fear_col  = _pick(df, ['Market_Fear_Level', 'Market_Fear_Level_x'])
    print(f"  Schema: stdev={stdev_col}, vix={vix_col}, fear={fear_col}")

    # ---- Encode categoricals ----
    df['RAS_Signal_Num']   = df['RAS_Signal'].map({'BUY': 1, 'HOLD': 0, 'SELL': -1}).fillna(0)
    df['Market_Fear_Num']  = df[fear_col].map({'Complacency / Calm': 0, 'High Volatility': 1}).fillna(0)
    
    has_sector_regime = 'Sector_Regime' in df.columns
    if has_sector_regime:
        df['Sector_Regime_Num'] = df['Sector_Regime'].map({'BULL_REGIME': 1, 'BEAR_REGIME': -1}).fillna(0)
    
    has_sector_momentum = 'Sector_Momentum_Score' in df.columns

    # Analyst consensus (new column — optional)
    has_analyst = 'Analyst_Consensus' in df.columns
    if has_analyst:
        ac_map = {'Strong Buy': 2, 'Buy': 1, 'Hold': 0, 'Sell': -1, 'Strong Sell': -2}
        df['Analyst_Consensus_Num'] = df['Analyst_Consensus'].map(ac_map).fillna(0)
        print("  Analyst_Consensus detected — adding as predictor")

    has_upside = 'Analyst_Upside_%' in df.columns

    # ---- Pivot tables ----
    return_pivot   = df.pivot(index='Date', columns='Ticker', values='Daily_Return_%')
    stdev_pivot    = df.pivot(index='Date', columns='Ticker', values=stdev_col)
    rsi_pivot      = df.pivot(index='Date', columns='Ticker', values='RSI_14d')
    adx_pivot      = df.pivot(index='Date', columns='Ticker', values='ADX_14d')
    plus_di_pivot  = df.pivot(index='Date', columns='Ticker', values='Plus_DI_14d')
    minus_di_pivot = df.pivot(index='Date', columns='Ticker', values='Minus_DI_14d')
    atr_pivot      = df.pivot(index='Date', columns='Ticker', values='ATR_14d')
    ras_pivot      = df.pivot(index='Date', columns='Ticker', values='RAS_Signal_Num')
    
    if has_sector_regime:
        sec_reg_pivot = df.pivot(index='Date', columns='Ticker', values='Sector_Regime_Num')
    if has_sector_momentum:
        sec_mom_pivot = df.pivot(index='Date', columns='Ticker', values='Sector_Momentum_Score')

    if has_analyst:
        ac_pivot = df.pivot(index='Date', columns='Ticker', values='Analyst_Consensus_Num')
    if has_upside:
        upside_pivot = df.pivot(index='Date', columns='Ticker', values='Analyst_Upside_%').fillna(0)

    std_adj_returns = return_pivot / (stdev_pivot + 1e-8)

    # ---- Build per-ticker predictor block ----
    predictors_list = []
    for t in std_adj_returns.columns:
        block = {
            f'{t}_RET_ADJ':  std_adj_returns[t],
            f'{t}_RSI':      rsi_pivot[t],
            f'{t}_ADX':      adx_pivot[t],
            f'{t}_PLUS_DI':  plus_di_pivot[t],
            f'{t}_MINUS_DI': minus_di_pivot[t],
            f'{t}_ATR':      atr_pivot[t],
            f'{t}_RAS':      ras_pivot[t],
        }
        if has_analyst:
            block[f'{t}_AC'] = ac_pivot[t]
        if has_upside:
            block[f'{t}_UPSIDE'] = upside_pivot[t]
        if has_sector_regime:
            block[f'{t}_SEC_REG'] = sec_reg_pivot[t]
        if has_sector_momentum:
            block[f'{t}_SEC_MOM'] = sec_mom_pivot[t]
        predictors_list.append(pd.DataFrame(block))

    all_predictors_df = pd.concat(predictors_list, axis=1)

    # ---- Macro features ----
    macro_df = (df.drop_duplicates(subset=['Date'])
                  .set_index('Date')[[vix_col, 'Market_Fear_Num']]
                  .rename(columns={vix_col: 'VIX_Close'}))
    all_predictors_df = pd.concat([all_predictors_df, macro_df], axis=1)

    # ---- Forward-fill then back-fill (standard financial data handling) ----
    all_predictors_df = all_predictors_df.ffill().bfill()

    return all_predictors_df, return_pivot, std_adj_returns, df, stdev_pivot


def prepare_sgp_data(target_series, predictors_df, lag, top_k=7):
    """
    Shift predictors, split train/test, select top_k features, standardize.
    Returns train/test arrays + metadata. Selective dropna (target only first).
    """
    shifted   = predictors_df.shift(lag)
    data_full = pd.concat([target_series, shifted], axis=1).replace([np.inf, -np.inf], np.nan)
    data_full = data_full[data_full.iloc[:, 0].notna()]

    split     = int(len(data_full) * 0.8)
    y_train_s = data_full.iloc[:split, 0]
    Xp_train  = data_full.iloc[:split, 1:]
    y_test_s  = data_full.iloc[split:, 0]
    Xp_test   = data_full.iloc[split:, 1:]

    corrs = Xp_train.corrwith(y_train_s).dropna()
    top_k_cols = corrs.abs().sort_values(ascending=False).head(top_k).index.tolist()

    train_clean = pd.concat([y_train_s, Xp_train[top_k_cols]], axis=1).dropna()
    test_clean  = pd.concat([y_test_s,  Xp_test[top_k_cols]],  axis=1).dropna()

    y_train = train_clean.iloc[:, 0].values
    Xt      = train_clean.iloc[:, 1:].values
    y_test  = test_clean.iloc[:, 0].values
    Xe      = test_clean.iloc[:, 1:].values

    Xm = Xt.mean(0);  Xs = Xt.std(0) + 1e-8
    Xt_s = (Xt - Xm) / Xs;  Xe_s = (Xe - Xm) / Xs

    return (y_train, Xt_s, y_test, Xe_s, test_clean.index, top_k_cols, Xm, Xs)
