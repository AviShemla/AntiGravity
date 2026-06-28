import sys

f = r'C:\Users\AviShemla\AntiGravity\intraday_tracker.py'
with open(f, 'r', encoding='utf-8') as file:
    content = file.read()
    
# Safely encode to ASCII to drop all emojis, then decode back
clean_content = content.encode('ascii', 'ignore').decode('ascii')

with open(f, 'w', encoding='utf-8') as file:
    file.write(clean_content)
    
print('All unicode characters stripped!')
