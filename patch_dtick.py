import re

with open("frontend/app.js", "r", encoding="utf-8") as f:
    content = f.read()

# Remove the invalid tickformat, tickmode, and dtick properties when type is 'category'
# These properties break categorical axes in Plotly by treating strings as millisecond intervals
content = re.sub(
    r'tickformat:\s*"%d/%m/%Y",\s*tickmode:\s*"linear",\s*dtick:\s*86400000,\s*',
    '',
    content
)

with open("frontend/app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Patched app.js successfully.")
