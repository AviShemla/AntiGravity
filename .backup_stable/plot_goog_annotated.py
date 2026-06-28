import pandas as pd
import matplotlib.pyplot as plt
import os

input_file = r'C:\Users\AviShemla\AntiGravity\Nasdaq_Data_All_Sectors_Combined.csv'
output_plot = r'C:\Users\AviShemla\AntiGravity\goog_googl_lagged_annotated.png'

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])

# Filter for the last 2 months
last_date = df['Date'].max()
start_date = last_date - pd.DateOffset(months=2)

goog_data = df[(df['Ticker'] == 'GOOG') & (df['Date'] >= start_date)].sort_values('Date').copy()
googl_data_all = df[df['Ticker'] == 'GOOGL'].sort_values('Date').copy()

# Create the lagged predictor for GOOGL (shift by 1)
googl_data_all['Lagged_Date'] = googl_data_all['Date']
googl_data_all['Lagged_Price'] = googl_data_all['Close']
googl_data_all['Join_Date'] = googl_data_all['Date'].shift(-1) # Join Date T-1 with Date T

# Merge GOOG(T) with GOOGL(T-1)
merged = pd.merge(goog_data, googl_data_all[['Join_Date', 'Lagged_Date', 'Lagged_Price']], 
                  left_on='Date', right_on='Join_Date', how='inner')

print(f"Plotting {len(merged)} annotated points...")

plt.figure(figsize=(20, 12))
plt.plot(merged['Date'], merged['Close'], label='GOOG (Target t)', color='blue', marker='o', linewidth=2)
plt.plot(merged['Lagged_Date'], merged['Lagged_Price'], label='GOOGL (Predictor t-1)', color='orange', marker='x', linestyle='--', alpha=0.5)

# Annotate each GOOG marker
for i, row in merged.iterrows():
    label = f"Used: {row['Lagged_Date'].date()}\nPrice: ${row['Lagged_Price']:.2f}"
    plt.annotate(label, 
                 xy=(row['Date'], row['Close']),
                 xytext=(5, 5), 
                 textcoords='offset points',
                 fontsize=10,
                 color='darkblue',
                 bbox=dict(boxstyle='round,pad=0.2', fc='yellow', alpha=0.3))

plt.title(f'GOOG vs Lagged GOOGL (Lag: 1 Day) - Annotated', fontsize=22)
plt.xlabel('Date of GOOG', fontsize=16)
plt.ylabel('Closing Price (USD)', fontsize=16)
plt.legend()
plt.grid(True, which='both', linestyle='--', alpha=0.3)
plt.xticks(rotation=45)

plt.tight_layout()
plt.savefig(output_plot)
print(f"Plot saved to {output_plot}")
