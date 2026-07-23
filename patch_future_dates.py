import re

with open("server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix /api/race
content = re.sub(
    r"pd\.date_range\(start=plot_df\.index\.min\(\), end=pd\.Timestamp\.now\(\)\.normalize\(\)",
    "pd.date_range(start=plot_df.index.min(), end=plot_df.index.max()",
    content
)

# Fix /api/olympic
content = re.sub(
    r"pd\.date_range\(start=df_merged\.index\.min\(\), end=pd\.Timestamp\.now\(\)\.normalize\(\)",
    "pd.date_range(start=df_merged.index.min(), end=df_merged.index.max()",
    content
)

# Fix /api/prod_shadow
content = re.sub(
    r"pd\.date_range\(start=df\['Date'\]\.min\(\), end=pd\.Timestamp\.now\(\)\.normalize\(\)",
    "pd.date_range(start=df['Date'].min(), end=df['Date'].max()",
    content
)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Removed future-date injection.")
