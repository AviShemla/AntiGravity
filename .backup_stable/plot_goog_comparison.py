import pandas as pd
import matplotlib.pyplot as plt
import os

input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Nasdaq_Data_All_Sectors_Combined.csv')
output_plot = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'goog_googl_last_2_months.png')

print("Reading data...")
df = pd.read_csv(input_file)
df['Date'] = pd.to_datetime(df['Date'])

# Filter for the last 2 months
last_date = df['Date'].max()
start_date = last_date - pd.DateOffset(months=2)

goog_data = df[(df['Ticker'] == 'GOOG') & (df['Date'] >= start_date)].sort_values('Date')
googl_data = df[(df['Ticker'] == 'GOOGL') & (df['Date'] >= start_date)].sort_values('Date')

print(f"Plotting from {start_date.date()} to {last_date.date()}")

# Set up the plot
plt.figure(figsize=(14, 7))
plt.plot(goog_data['Date'], goog_data['Close'], label='GOOG (Class C)', alpha=0.8, linewidth=2, marker='o')
plt.plot(googl_data['Date'], googl_data['Close'], label='GOOGL (Class A)', alpha=0.8, linewidth=2, linestyle='--', marker='x')

plt.xlim(start_date, last_date) # Explicitly set limits

plt.title(f'GOOG vs GOOGL Comparison ({start_date.date()} to {last_date.date()})', fontsize=16)
plt.xlabel('Date', fontsize=12)
plt.ylabel('Closing Price (USD)', fontsize=12)
plt.legend()
plt.grid(True, which='both', linestyle='--', alpha=0.5)

plt.tight_layout()
plt.savefig(output_plot)
print(f"Plot saved to {output_plot}")

# Modern styling
plt.style.use('seaborn-v0_8-muted') # If available, otherwise it falls back
plt.tight_layout()

# Save the plot
plt.savefig(output_plot)
print(f"Plot saved to {output_plot}")
