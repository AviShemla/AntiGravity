import os
import sys

f = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'intraday_tracker.py')
with open(f, 'r', encoding='utf-8') as file:
    content = file.read()
    
# Safely encode to ASCII to drop all emojis, then decode back
clean_content = content.encode('ascii', 'ignore').decode('ascii')

with open(f, 'w', encoding='utf-8') as file:
    file.write(clean_content)
    
print('All unicode characters stripped!')
