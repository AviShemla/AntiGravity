import sys

f = r'C:\Users\AviShemla\AntiGravity\intraday_tracker.py'
with open(f, 'r', encoding='utf-8') as file:
    content = file.read()
    
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'except' in line and i > 85 and i < 95:
        # Check if the next line is empty or just return
        if 'return' in lines[i+1]:
            lines[i+1] = '        pass'
            
content = '\n'.join(lines)

with open(f, 'w', encoding='utf-8') as file:
    file.write(content)
print('Fixed IndentationError again!')
