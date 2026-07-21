import re

with open('frontend/Architecture_Map.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix normal nodes: ID[text] -> ID["text"]
content = re.sub(r'([A-Z_0-9]+)\[([^"\]]+)\](:::)', r'\1["\2"]\3', content)

# Fix database nodes: ID[(text)] -> ID[("text")]
content = re.sub(r'([A-Z_0-9]+)\[\(\"?(.*?)\"?\)\](:::)', r'\1[("\2")]\3', content)

with open('frontend/Architecture_Map.html', 'w', encoding='utf-8') as f:
    f.write(content)
