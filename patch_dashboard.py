import sys
import pandas as pd

with open('dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update calculate_metrics
old_calc = """def calculate_metrics(df, persona):
    eq_col = f'{persona}_Total_Equity'
    pct_col = f'{persona}_Daily_Profit_%'
    
    if eq_col not in df.columns or pct_col not in df.columns or df.empty:
        return 0, 0, 0"""

new_calc = """def calculate_metrics(df, persona):
    if 'Total_Equity' in df.columns:
        eq_col = 'Total_Equity'
        pct_returns = df['Total_Equity'].pct_change().dropna()
    else:
        eq_col = f'{persona}_Total_Equity'
        if f'{persona}_Daily_Profit_%' in df.columns:
            pct_returns = df[f'{persona}_Daily_Profit_%'].dropna() / 100
        else:
            pct_returns = pd.Series(dtype=float)
            
    if eq_col not in df.columns or df.empty:
        return 0, 0, 0, 0"""

content = content.replace(old_calc, new_calc)

# Fix sharpe ratio calculation using pct_returns that we defined
old_sharpe = """    # Sharpe Ratio
    pct_returns = df[pct_col].dropna() / 100
    if len(pct_returns) > 1 and pct_returns.std() > 0:"""

new_sharpe = """    # Sharpe Ratio
    if len(pct_returns) > 1 and pct_returns.std() > 0:"""
    
content = content.replace(old_sharpe, new_sharpe)

# Fix win rate to ignore 0 returns (cash holding days)
old_win = """    # Win Rate
    if len(pct_returns) > 0:
        win_rate = (len(pct_returns[pct_returns > 0]) / len(pct_returns)) * 100"""

new_win = """    # Win Rate
    active_days = pct_returns[pct_returns != 0]
    if len(active_days) > 0:
        win_rate = (len(active_days[active_days > 0]) / len(active_days)) * 100"""

content = content.replace(old_win, new_win)

# 2. Update get_recent_trades
old_trades = """def get_recent_trades(df, persona, limit=5):
    h_col = f'{persona}_Holdings'
    if h_col not in df.columns or len(df) < 2:
        return []"""

new_trades = """def get_recent_trades(df, persona, limit=5):
    h_col = 'Holdings_JSON' if 'Holdings_JSON' in df.columns else f'{persona}_Holdings'
    if h_col not in df.columns or len(df) < 2:
        return []"""

content = content.replace(old_trades, new_trades)

# 3. Swap trial_path to ledger_path
content = content.replace(
    "trial_path = os.path.join(BASE_DIR, 'MultiPersona_Broker_30Day_Trial.xlsx')",
    "trial_path = os.path.join(BASE_DIR, f'Capital_Ledger_{persona_s}.csv')"
)
content = content.replace(
    "df_trial = pd.read_excel(trial_path, sheet_name='Daily Tracking')",
    "df_trial = pd.read_csv(trial_path)"
)
content = content.replace(
    "trial_path_e = os.path.join(BASE_DIR, 'MultiPersona_Broker_30Day_Trial_ETFs.xlsx')",
    "trial_path_e = os.path.join(BASE_DIR, f'ETF_Capital_Ledger_{persona_e}.csv')"
)
content = content.replace(
    "df_etf_trial = pd.read_excel(trial_path_e, sheet_name='Daily Tracking')",
    "df_etf_trial = pd.read_csv(trial_path_e)"
)

# 4. Fix DataFrame columns in UI
content = content.replace(
    "p_cols = ['Date', f'{persona_s_ui}_Total_Equity', f'{persona_s_ui}_Daily_Profit_$', f'{persona_s_ui}_Daily_Profit_%', f'{persona_s_ui}_Holdings']",
    "p_cols = ['Date', 'Total_Equity', 'Cash', 'Daily_PnL_JSON', 'Holdings_JSON']"
)
content = content.replace(
    "p_cols_e = ['Date', f'{persona_e_ui}_Total_Equity', f'{persona_e_ui}_Daily_Profit_$', f'{persona_e_ui}_Daily_Profit_%', f'{persona_e_ui}_Holdings']",
    "p_cols_e = ['Date', 'Total_Equity', 'Cash', 'Daily_PnL_JSON', 'Holdings_JSON']"
)

# 5. Fix equity plots to use Total_Equity instead of Persona_Total_Equity
old_eq_cols = """                    eq_cols = [c for c in df_trial.columns if 'Equity' in c]
                    if eq_cols and 'Date' in df_trial.columns:
                        df_trial['Date'] = pd.to_datetime(df_trial['Date'])
                        plot_df = df_trial[['Date'] + eq_cols].copy()"""

new_eq_cols = """                    eq_cols = ['Total_Equity'] if 'Total_Equity' in df_trial.columns else [c for c in df_trial.columns if 'Equity' in c]
                    if eq_cols and 'Date' in df_trial.columns:
                        df_trial['Date'] = pd.to_datetime(df_trial['Date'])
                        plot_df = df_trial[['Date'] + eq_cols].copy()"""
content = content.replace(old_eq_cols, new_eq_cols)

old_eq_cols_e = """                    eq_cols_e = [c for c in df_etf_trial.columns if 'Equity' in c]
                    if eq_cols_e and 'Date' in df_etf_trial.columns:
                        df_etf_trial['Date'] = pd.to_datetime(df_etf_trial['Date'])
                        plot_df_e = df_etf_trial[['Date'] + eq_cols_e].copy()"""

new_eq_cols_e = """                    eq_cols_e = ['Total_Equity'] if 'Total_Equity' in df_etf_trial.columns else [c for c in df_etf_trial.columns if 'Equity' in c]
                    if eq_cols_e and 'Date' in df_etf_trial.columns:
                        df_etf_trial['Date'] = pd.to_datetime(df_etf_trial['Date'])
                        plot_df_e = df_etf_trial[['Date'] + eq_cols_e].copy()"""
content = content.replace(old_eq_cols_e, new_eq_cols_e)


with open('dashboard.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Dashboard patched successfully!")
