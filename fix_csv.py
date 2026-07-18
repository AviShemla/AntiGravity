import pandas as pd
csv_path = 'C:/Users/AviShemla/AntiGravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv'
df = pd.read_csv(csv_path)

# Drop the flatlined rows
df = df[~df['Date'].str.contains('2026-07-16|2026-07-17')]

df.to_csv(csv_path, index=False)
print("CSV fixed!")
