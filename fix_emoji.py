import sys

f = r'C:\Users\AviShemla\AntiGravity\intraday_tracker.py'
with open(f, 'r', encoding='utf-8') as file:
    content = file.read()
    
# Remove any problematic emojis from the print statements
content = content.replace('?', '[OK]')
content = content.replace('??', '[DOWN]')
content = content.replace('??', '[NO]')
content = content.replace('??', '[STOP]')
content = content.replace('??', '[ALERT]')
content = content.replace('??', '[UP]')

with open(f, 'w', encoding='utf-8') as file:
    file.write(content)
print('Emojis removed!')
