import pandas as pd
df = pd.read_excel('C:/Users/AviShemla/AntiGravity/financial_data/Top5_Bayesian_Scorecard_Formatted.xlsx', sheet_name=None, skiprows=2)
for sheet, data in df.items():
    date_col = 'date' if 'date' in data.columns else 'Date' if 'Date' in data.columns else None
    if date_col:
        print(f"Sheet {sheet}: {data[date_col].dropna().astype(str).tolist()[-5:]}")
