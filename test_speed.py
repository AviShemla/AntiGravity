import time
import failover_downloader as fd
import pandas as pd
import numpy as np
import datetime
import pandas_market_calendars as mcal

def profile():
    t0 = time.time()
    ticker = 'AAPL'
    start = '2026-07-15'
    
    t1 = time.time()
    print("Startup overhead:", t1-t0)
    
    ticker_api = ticker.replace('.', '-')
    df = fd._fetch_yf_global(ticker_api, start, None)
    t2 = time.time()
    print("_fetch_yf_global overhead:", t2-t1)
    
    nyse = mcal.get_calendar('NYSE')
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    valid_days = nyse.valid_days(start_date=(datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d'), end_date=today)
    
    t3 = time.time()
    print("mcal overhead:", t3-t2)
    
profile()
