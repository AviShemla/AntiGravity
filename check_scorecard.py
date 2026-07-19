import pandas as pd
import os

filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'MultiPersona_Broker_30Day_Trial.xlsx')
df = pd.read_excel(filepath, sheet_name="Neutral")
print("MultiPersona Neutral last row:")
print(df.tail(1)[['Date', 'Holdings_JSON']])

filepath_etf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data', 'ETF_Broker_30Day_Trial.xlsx')
df_etf = pd.read_excel(filepath_etf, sheet_name="ETF_Neutral")
print("\nETF_Broker ETF_Neutral last row:")
print(df_etf.tail(1)[['Date', 'Holdings_JSON']])
