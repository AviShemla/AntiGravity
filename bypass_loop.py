import os
import sys
import datetime

f = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'intraday_tracker.py')
with open(f, 'r', encoding='utf-8') as file:
    content = file.read()
    
# Fast way to just break out of the infinite loop once it does a single iteration
content = content.replace('if not pending_orders:', 'if not pending_orders:\n            print("No pending orders.")')
content = content.replace('print("Market is closed. Sleeping 60s...")\n            time.sleep(60)', 'print("Market closed. Exiting.")\n            break')

# Also forcefully set is_eod_fallback to True inside the open market branch so it commits the ledger
content = content.replace('is_eod_fallback = False', 'is_eod_fallback = True')

# Replace while True with a 1-time run
content = content.replace('while True:', 'for _ in range(1):')

with open(f, 'w', encoding='utf-8') as file:
    file.write(content)
print('Intraday tracker loop bypassed via UTF-8 script!')
