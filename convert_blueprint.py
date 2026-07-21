import markdown
import os
import re

md_path = r"C:\Users\AviShemla\AntiGravity\AntiGravity_Master_Blueprint.md"
docx_path = r"C:\Users\AviShemla\Desktop\AntiGravity_Master_Blueprint.doc"

with open(md_path, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix Mermaid blocks because standard markdown doesn't parse them into something Word likes.
# We'll just leave them as raw text in a pre block for now.
html = markdown.markdown(text, extensions=['fenced_code', 'tables'])

# Add basic HTML structure so Word opens it properly
full_html = f"""<html>
<head><meta charset='utf-8'><title>AntiGravity Master Blueprint</title>
<style>
body {{ font-family: Calibri, sans-serif; font-size: 11pt; padding: 20px; }}
h1 {{ color: #2F5496; border-bottom: 2px solid #2F5496; }}
h2 {{ color: #2F5496; border-bottom: 1px solid #2F5496; }}
h3 {{ color: #4472C4; }}
blockquote {{ color: #C00000; font-weight: bold; border-left: 3px solid #C00000; padding-left: 10px; background-color: #F9F9F9; }}
a {{ color: #0563C1; text-decoration: underline; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
th, td {{ border: 1px solid #DDDDDD; text-align: left; padding: 8px; }}
th {{ background-color: #F2F2F2; }}
pre {{ background-color: #F4F4F4; padding: 10px; border-radius: 5px; font-family: Consolas, monospace; }}
</style>
</head>
<body>
{html}
</body>
</html>"""

with open(docx_path, 'w', encoding='utf-8') as f:
    f.write(full_html)
print(f"Saved Blueprint HTML as DOC to {docx_path}")
