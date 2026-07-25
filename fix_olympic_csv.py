import pandas as pd

path = "C:/Users/AviShemla/AntiGravity/financial_data/Prod_vs_Shadow_Results_MASTER.csv"
df = pd.read_csv(path)
df = df.drop_duplicates(subset=["Date"], keep="last")
df.to_csv(path, index=False)
print("Duplicate dates removed from Olympic CSV.")
