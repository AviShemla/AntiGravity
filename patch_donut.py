import sys

with open('dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_str = "texttemplate='<b>%{label}</b> (%{percent})'"
new_str = "texttemplate='<b>%{label}</b><br>$%{value:,.0f} (%{percent})'"

content = content.replace(old_str, new_str)

with open('dashboard.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Donut pie charts patched successfully!")
