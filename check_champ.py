import pandas as pd

df_live = pd.read_excel('C:/Users/AviShemla/AntiGravity/financial_data/Top5_Bayesian_Scorecard_Formatted.xlsx', sheet_name=None)
champ_tickers = []
for sheet, df_s in df_live.items():
    if 'Engine_Conviction' in df_s.columns:
        ticks = df_s.nlargest(5, 'Engine_Conviction')['Ticker'].tolist()
        champ_tickers.extend(ticks)
        
champ_tickers.extend(ticks[:15])
print(len(list(set(champ_tickers))))
