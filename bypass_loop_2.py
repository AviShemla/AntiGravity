import os
import sys

f = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'intraday_tracker.py')
with open(f, 'r', encoding='utf-8') as file:
    content = file.read()
    
# Completely bypass the time check so it acts like the market is open and runs exactly 1 iteration
content = content.replace('if is_weekday and (market_open <= now_ny <= market_close):', 'if True: # FORCED BYPASS')

with open(f, 'w', encoding='utf-8') as file:
    file.write(content)
print('Forced market to behave as OPEN!')
