import pandas as pd
df = pd.read_excel("financial_data/Top5_Bayesian_Scorecard_Formatted.xlsx", sheet_name=0, skiprows=2)
print("LAST ROW DATE:")
print(df['Date'].iloc[-1])
