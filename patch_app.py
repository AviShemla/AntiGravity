with open('frontend/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("xaxis: { color:", "xaxis: { type: 'category', tickangle: 0, color:")
content = content.replace("xaxis: { \n", "xaxis: { type: 'category', tickangle: 0, \n")

with open('frontend/app.js', 'w', encoding='utf-8') as f:
    f.write(content)
print("app.js patched successfully.")
