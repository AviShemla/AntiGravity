import sys

f = r'C:\Users\AviShemla\AntiGravity\intraday_tracker.py'
with open(f, 'r', encoding='utf-8') as file:
    content = file.read()
    
# Clean up any bad indents around line 97
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'return' in line and i > 90 and i < 105:
        # Just safely indent it to 4 spaces
        lines[i] = '    return'

content = '\n'.join(lines)

with open(f, 'w', encoding='utf-8') as file:
    file.write(content)
print('Fixed IndentationError!')
