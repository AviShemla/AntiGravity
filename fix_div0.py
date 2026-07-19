import os
import sys

files = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'virtual_broker.py'), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_virtual_broker.py')]

for f in files:
    with open(f, 'r') as file:
        content = file.read()
        
    content = content.replace('actual_return_pct = (close_price - purchase_price) / purchase_price', 'actual_return_pct = (close_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0')
    content = content.replace('intraday_drop = (low_price - purchase_price) / purchase_price', 'intraday_drop = (low_price - purchase_price) / purchase_price if purchase_price > 0 else 0.0')
    
    with open(f, 'w') as file:
        file.write(content)
        
print('Fixed division by 0!')
