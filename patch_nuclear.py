import re

# 1. Patch app.js to use type: 'category' instead of 'date'
with open("frontend/app.js", "r", encoding="utf-8") as f:
    js_content = f.read()

# Replace 'date' with 'category' in all xaxis definitions
js_content = re.sub(
    r"type:\s*'date'",
    "type: 'category'",
    js_content
)

with open("frontend/app.js", "w", encoding="utf-8") as f:
    f.write(js_content)

# 2. Patch server.py to output '%d/%m/%Y' instead of '%Y-%m-%d'
with open("server.py", "r", encoding="utf-8") as f:
    py_content = f.read()

# For /api/race
py_content = re.sub(
    r"plot_df\.index\.strftime\('%Y-%m-%d'\)",
    "plot_df.index.strftime('%d/%m/%Y')",
    py_content
)
py_content = re.sub(
    r"norm_spy\.index\.strftime\('%Y-%m-%d'\)",
    "norm_spy.index.strftime('%d/%m/%Y')",
    py_content
)

# For /api/olympic
py_content = re.sub(
    r"df_merged\.index\.strftime\('%Y-%m-%d'\)",
    "df_merged.index.strftime('%d/%m/%Y')",
    py_content
)

# For /api/prod_shadow
py_content = re.sub(
    r"df\['Date'\]\.dt\.strftime\('%Y-%m-%d'\)",
    "df['Date'].dt.strftime('%d/%m/%Y')",
    py_content
)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(py_content)

print("Nuclear JS/Python Category Patch applied locally.")
