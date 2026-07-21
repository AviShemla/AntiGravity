import markdown
import os

md_path = r"C:\Users\AviShemla\.gemini\antigravity\brain\cfc7c743-b169-4b8b-a5e8-6c10348c0c51\implementation_plan.md"
docx_path = r"C:\Users\AviShemla\Desktop\Vultr_Migration_Blueprint.doc"

with open(md_path, 'r', encoding='utf-8') as f:
    text = f.read()

html = markdown.markdown(text)

# Add basic HTML structure so Word opens it properly
full_html = f"""<html>
<head><meta charset='utf-8'><title>Vultr Migration Blueprint</title>
<style>
body {{ font-family: Calibri, sans-serif; font-size: 11pt; }}
h1, h2, h3 {{ color: #2F5496; }}
blockquote {{ color: red; font-weight: bold; border-left: 2px solid red; padding-left: 10px; }}
a {{ color: blue; text-decoration: underline; }}
</style>
</head>
<body>
{html}
</body>
</html>"""

with open(docx_path, 'w', encoding='utf-8') as f:
    f.write(full_html)
print(f"Saved HTML as DOC to {docx_path}")
