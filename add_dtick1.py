import re

with open("frontend/app.js", "r", encoding="utf-8") as f:
    content = f.read()

# Add dtick: 1 to all category axes to force Plotly to show EVERY single category (no auto-thinning)
content = re.sub(
    r"xaxis:\s*\{\s*type:\s*'category',\s*tickangle:\s*-45,\s*color:\s*'white',",
    r"xaxis: { type: 'category', dtick: 1, tickangle: -45, color: 'white',",
    content
)

with open("frontend/app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Added dtick: 1 to app.js")
