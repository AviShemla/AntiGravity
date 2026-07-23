import re

with open("server.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Fix /api/race
content = re.sub(
    r"plot_df\.reindex\(pd\.date_range\(start=plot_df\.index\.min\(\), end=plot_df\.index\.max\(\), freq='B'\)\)\.ffill\(\)",
    "plot_df.reindex(pd.date_range(start=plot_df.index.min(), end=max(plot_df.index.max(), pd.Timestamp.now().normalize() - pd.offsets.BDay(1)), freq='B')).ffill()",
    content
)

# 2. Fix /api/olympic
content = re.sub(
    r"df_merged\.reindex\(pd\.date_range\(start=df_merged\.index\.min\(\), end=df_merged\.index\.max\(\), freq='B'\)\)\.ffill\(\)",
    "df_merged.reindex(pd.date_range(start=df_merged.index.min(), end=max(df_merged.index.max(), pd.Timestamp.now().normalize() - pd.offsets.BDay(1)), freq='B')).ffill()",
    content
)

# 3. Fix /api/holdings
# Find: 
#     df['Date'] = pd.to_datetime(df['Date'])
#     dates = df['Date'].dt.strftime('%d/%m/%Y').tolist()
#     equity_curve = df['Total_Equity'].tolist()

replacement = """
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date').reindex(pd.date_range(start=df['Date'].min(), end=max(df['Date'].max(), pd.Timestamp.now().normalize() - pd.offsets.BDay(1)), freq='B')).ffill().reset_index().rename(columns={'index': 'Date'})
    dates = df['Date'].dt.strftime('%d/%m/%Y').tolist()
    equity_curve = df['Total_Equity'].tolist()
"""
content = re.sub(
    r"    df\['Date'\] = pd\.to_datetime\(df\['Date'\]\)\n    dates = df\['Date'\].dt.strftime\('%d/%m/%Y'\)\.tolist\(\)\n    equity_curve = df\['Total_Equity'\]\.tolist\(\)",
    replacement.strip('\n'),
    content
)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Patch applied.")
