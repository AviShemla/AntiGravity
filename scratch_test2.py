import urllib.request, json, yfinance as yf

tkrs = ['NDAQ', 'MCD', 'NEE', 'MSTZ']
d = yf.download(tkrs, period='2d', progress=False)['Close']
prices = ((d.iloc[-1] / d.iloc[0]) - 1) * 100

print("LIVE INTRADAY PRICES:", prices.to_dict())

personas = ['Conservative', 'Neutral', 'Dynamic']
for p in personas:
    res = urllib.request.urlopen(f"http://localhost/api/holdings?persona={p}&mode=Single").read()
    print(f"{p} Stocks Allocations: {json.loads(res)['allocations']}")
    
    res = urllib.request.urlopen(f"http://localhost/api/holdings?persona={p}&mode=ETF").read()
    print(f"{p} ETFs Allocations: {json.loads(res)['allocations']}")
