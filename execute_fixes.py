import os
import re

# 1. Update AGENTS.md rules
agents_path = ".agents/AGENTS.md"
new_rules = """
## Dashboard UI Architecture Rule
The dashboard is ONLY located in the modern Javascript stack (`frontend/app.js` and `server.py`). The legacy Streamlit scripts (`dashboard.py` or `dashboard_v1.py`) are strictly abandoned. DO NOT attempt to patch or view them.

## Orchestration & Scheduling Rule
Schedule orchestration is ONLY run via Vultr and Prefect. NEVER use local master_watchdog.py, cron, or schedule manager scripts locally on the laptop. 

## Production Database Constraint
Production Database is ONLY Turso. The system must never rely on local SQLite for true production data or state changes unless explicitly handling local fallbacks.
"""

if os.path.exists(agents_path):
    with open(agents_path, "a", encoding="utf-8") as f:
        f.write(new_rules)
    print("AGENTS.md updated.")

# 2. Patch server.py
with open("server.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix /api/race
content = re.sub(
    r'([ \t]+)plot_df = pd\.concat\(all_ledgers, axis=1\)\.sort_index\(\)\.ffill\(\)',
    r"\1plot_df = pd.concat(all_ledgers, axis=1).sort_index().ffill()\n\1plot_df.index = pd.to_datetime(plot_df.index)\n\1plot_df = plot_df.reindex(pd.date_range(start=plot_df.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()",
    content
)

# Fix /api/olympic
content = re.sub(
    r'([ \t]+)df_merged = df_merged\.ffill\(\)',
    r"\1df_merged = df_merged.ffill()\n\1df_merged.index = pd.to_datetime(df_merged.index)\n\1df_merged = df_merged.reindex(pd.date_range(start=df_merged.index.min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill()",
    content
)

# Fix /api/prod_shadow (Shadow LSTM)
content = content.replace(
    "df = df.ffill().fillna(10000.0)",
    "df = df.ffill().fillna(10000.0)\n    if 'Date' in df.columns:\n        df['Date'] = pd.to_datetime(df['Date'])\n        df = df.set_index('Date').reindex(pd.date_range(start=df['Date'].min(), end=pd.Timestamp.now().normalize(), freq='B')).ffill().reset_index().rename(columns={'index': 'Date'})\n        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')"
)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(content)
print("server.py patched.")

# 3. Patch app.js
with open("frontend/app.js", "r", encoding="utf-8") as f:
    js_content = f.read()

# Replace all occurrences of xaxis date configurations
js_content = re.sub(
    r"xaxis:\s*\{\s*type:\s*'date',\s*tickangle:\s*0,\s*color:\s*'white',\s*gridcolor:\s*'rgba\(255,255,255,0\.1\)'(?:,\s*rangeslider:\s*\{\s*visible:\s*true[^}]*\}\s*)?\}",
    "xaxis: { type: 'date', tickformat: \"%d/%m/%Y\", tickmode: \"linear\", dtick: 86400000, tickangle: -45, color: 'white', gridcolor: 'rgba(255,255,255,0.1)', rangeslider: { visible: true, thickness: 0.08, bgcolor: '#383838', bordercolor: '#1E90FF', borderwidth: 1 } }",
    js_content
)

js_content = re.sub(
    r"xaxis:\s*\{\s*type:\s*'date',\s*tickangle:\s*0,\s*",
    "xaxis: { type: 'date', tickformat: \"%d/%m/%Y\", tickmode: \"linear\", dtick: 86400000, tickangle: -45, ",
    js_content
)

with open("frontend/app.js", "w", encoding="utf-8") as f:
    f.write(js_content)
print("app.js patched.")
