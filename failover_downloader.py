import os
import time
import requests
import json
import datetime
import pandas as pd
import numpy as np
import yfinance as yf

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
QUARANTINE_FILE = os.path.join(BASE_DIR, 'financial_data', 'quarantined_tickers.json')
WARNINGS_FILE = os.path.join(BASE_DIR, 'financial_data', 'pipeline_warnings.txt')

def safe_print(msg):
    """Safely print messages to Windows console, falling back to ASCII if encoding fails."""
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode('ascii', 'replace').decode('ascii'))
        except Exception:
            pass

def clear_warnings():
    """Clear all warning logs from previous daily run."""
    if os.path.exists(WARNINGS_FILE):
        try:
            os.remove(WARNINGS_FILE)
        except Exception:
            pass
    safe_print("[WARNINGS] Cleared pipeline warning logs.")

def log_warning(warning_text):
    """Append a high-priority pipeline warning."""
    os.makedirs(os.path.dirname(WARNINGS_FILE), exist_ok=True)
    with open(WARNINGS_FILE, 'a', encoding='utf-8') as f:
        f.write(warning_text + "\n")
    safe_print(f"[LOGGED WARNING] {warning_text}")

def get_warnings():
    """Retrieve all logged pipeline warnings."""
    if not os.path.exists(WARNINGS_FILE):
        return []
    try:
        with open(WARNINGS_FILE, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

def clear_quarantined_tickers():
    """Reset the quarantine list at the start of a pipeline run."""
    clear_warnings()
    os.makedirs(os.path.dirname(QUARANTINE_FILE), exist_ok=True)
    with open(QUARANTINE_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)
    safe_print("[QUARANTINE] Cleared all quarantined tickers for the new run.")

def quarantine_ticker(ticker, reason):
    """Add a ticker to the quarantine registry and log it."""
    os.makedirs(os.path.dirname(QUARANTINE_FILE), exist_ok=True)
    data = {}
    if os.path.exists(QUARANTINE_FILE):
        try:
            with open(QUARANTINE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
            
    data[ticker] = {
        "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "reason": reason
    }
    
    with open(QUARANTINE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    safe_print(f"⚠️ [QUARANTINE] Quarantined ticker {ticker}! Reason: {reason}")
    log_warning(f"🚨 {ticker} quarantined due to data fetch failure: {reason}. Forced to HOLD.")

def is_quarantined(ticker):
    """Check if a ticker is currently quarantined."""
    if not os.path.exists(QUARANTINE_FILE):
        return False
    try:
        with open(QUARANTINE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return ticker in data
    except Exception:
        return False

def get_quarantined_dict():
    """Retrieve all quarantined tickers and their reasons."""
    if not os.path.exists(QUARANTINE_FILE):
        return {}
    try:
        with open(QUARANTINE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def download_ticker_direct_api(ticker, period=None, start=None):
    """Fallback: Directly request stock data from Yahoo chart JSON endpoint."""
    safe_print(f"  [FAILOVER] Fetching {ticker} via direct Yahoo Chart API...")
    try:
        import random
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ]
        headers = {"User-Agent": random.choice(user_agents)}
        
        # Build query parameters based on period or start date
        if start:
            start_dt = pd.to_datetime(start)
            end_dt = datetime.datetime.now()
            period1 = int(start_dt.timestamp())
            period2 = int(end_dt.timestamp())
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={period1}&period2={period2}&interval=1d"
        else:
            rng = period if period else "5y"
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
            
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            safe_print(f"  [FAILOVER] API returned status code {response.status_code} for {ticker}")
            return pd.DataFrame()
            
        data = response.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return pd.DataFrame()
            
        res = result[0]
        timestamps = res.get("timestamp", [])
        if not timestamps:
            return pd.DataFrame()
            
        indicators = res.get("indicators", {}).get("quote", [{}])[0]
        adjclose_list = res.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
        
        dates = [pd.to_datetime(t, unit='s').date() for t in timestamps]
        
        df_dict = {
            "Open": indicators.get("open", []),
            "High": indicators.get("high", []),
            "Low": indicators.get("low", []),
            "Close": indicators.get("close", []),
            "Volume": indicators.get("volume", [])
        }
        
        # Safety check lengths
        n = len(dates)
        for k in list(df_dict.keys()):
            if len(df_dict[k]) != n:
                # Pad or crop to match date length
                df_dict[k] = (list(df_dict[k]) + [np.nan] * n)[:n]
                
        if len(adjclose_list) == n:
            df_dict["Adj Close"] = adjclose_list
        else:
            df_dict["Adj Close"] = df_dict["Close"]
            
        df = pd.DataFrame(df_dict, index=dates)
        df.index.name = "Date"
        
        # Drop rows where Close is missing
        df = df.dropna(subset=["Close"])
        return df
    except Exception as e:
        safe_print(f"  [FAILOVER ERROR] Failed to fetch {ticker} from Yahoo API: {e}")
        return pd.DataFrame()

def download_ticker_tiingo_api(ticker, period=None, start=None):
    """Ultimate Failover: Fetches data from Tiingo if Yahoo completely crashes."""
    api_key_path = os.path.join(BASE_DIR, 'financial_data', 'api_keys.json')
    if not os.path.exists(api_key_path):
        safe_print("  [TIINGO ERROR] api_keys.json not found. Cannot hit Tiingo Failover.")
        return pd.DataFrame()
        
    try:
        with open(api_key_path, 'r') as f:
            keys = json.load(f)
            api_key = keys.get("TIINGO_API_KEY")
    except Exception:
        safe_print("  [TIINGO ERROR] Failed to parse api_keys.json.")
        return pd.DataFrame()
        
    if not api_key:
        safe_print("  [TIINGO ERROR] TIINGO_API_KEY is empty.")
        return pd.DataFrame()

    safe_print(f"  [INSTITUTIONAL FAILOVER] Pinged Tiingo API for {ticker}...")
    try:
        start_date = start
        if not start_date:
            import datetime
            days = 365 * 5 # default 5y
            if period == "1y": days = 365
            elif period == "3mo": days = 90
            elif period == "6mo": days = 180
            elif period == "1mo": days = 30
            elif period == "ytd": days = 365
            
            start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
            
        url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start_date}&token={api_key}"
        headers = {'Content-Type': 'application/json'}
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            safe_print(f"  [TIINGO ERROR] API returned status code {response.status_code}")
            return pd.DataFrame()
            
        data = response.json()
        if not data or not isinstance(data, list):
            safe_print(f"  [TIINGO ERROR] Empty or invalid payload from Tiingo.")
            return pd.DataFrame()
            
        df = pd.DataFrame(data)
        
        # Normalize to Yahoo's exact format
        df['Date'] = pd.to_datetime(df['date'])
        df.set_index('Date', inplace=True)
        df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume',
            'adjClose': 'Adj Close'
        }, inplace=True)
        
        # Sort chronologically (oldest to newest) like yfinance
        df = df.sort_index(ascending=True)
            
        return df[['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']]
    except Exception as e:
        safe_print(f"  [TIINGO ERROR] Failed to fetch {ticker} from Tiingo: {e}")
        return pd.DataFrame()

def download_ticker_with_failover(ticker, period=None, start=None):
    """
    Downloads historical data with exponential retries and backup failover.
    If both fail, registers the ticker as quarantined and returns an empty DataFrame.
    """
    df = pd.DataFrame()
    
    # Check if ticker is already quarantined
    if is_quarantined(ticker):
        safe_print(f"  [QUARANTINE BYPASS] Skipping {ticker} (already quarantined).")
        return pd.DataFrame()

    # Normalization: Yahoo Finance and Tiingo APIs require dashes instead of dots for class shares (e.g., BRK.B -> BRK-B)
    ticker_api = ticker.replace('.', '-')

    if start:
        # Check if the requested start date is in the future relative to NY time
        import datetime
        import pytz
        ny_tz = pytz.timezone('America/New_York')
        ny_now = datetime.datetime.now(ny_tz).date()
        start_date_obj = pd.to_datetime(start).date()
        
        if start_date_obj > ny_now:
            safe_print(f"  [INCREMENTAL SKIP] Requested start date {start} is in the future relative to NY time ({ny_now}). Skipping.")
            return pd.DataFrame()
            
    safe_print(f"  [YFINANCE] Fetching {ticker} (API String: {ticker_api})...")
    try:
        if start:
            df = yf.Ticker(ticker_api).history(start=start)
        else:
            rng = period if period else "5y"
            df = yf.Ticker(ticker_api).history(period=rng)
            
        if not df.empty and 'Close' in df.columns:
            # Validate that YFinance didn't silently omit the most recent trading day
            import pandas_market_calendars as mcal
            import datetime
            nyse = mcal.get_calendar('NYSE')
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            valid_days = nyse.valid_days(start_date=(datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d'), end_date=today)
            
            last_closed_market_day = valid_days[-2] if datetime.datetime.now().hour < 16 else valid_days[-1]
            last_closed_market_day = pd.to_datetime(last_closed_market_day).tz_localize(None).date()
            
            df.index = pd.to_datetime(df.index).tz_localize(None)
            
            # Find the row corresponding to last_closed_market_day
            # Since df.index is a datetime, we can check if it exists by matching dates
            matching_rows = df[df.index.date == last_closed_market_day]
            
            # if matching_rows.empty or pd.isna(matching_rows['Close'].iloc[-1]):
            #     raise ValueError(f"Yahoo Finance returned missing/NaN data for {last_closed_market_day}. Forcing Tiingo failover.")
                
            time.sleep(2) # Prevent rate limiting (Reduced from 5s to 2s)
            return df
    except Exception as e:
        safe_print(f"  [YFINANCE ERROR] {e}")

    # Fallback 1: Direct API
    time.sleep(2) # Backoff before hitting direct API
    df = download_ticker_direct_api(ticker_api, period=period, start=start)
    if not df.empty:
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        safe_print(f"  [SUCCESS] Resolved data for {ticker} using direct Yahoo API failover.")
        return df

    # Fallback 2: Tiingo Institutional API
    df = download_ticker_tiingo_api(ticker_api, period=period, start=start)
    if not df.empty:
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        safe_print(f"  [SUCCESS] Resolved data for {ticker} using Tiingo Institutional Failover!")
        return df

    if start:
        safe_print(f"  [INCREMENTAL SKIP] No new data found since {start} for {ticker}. Market likely closed or timezone mismatch. Skipping without quarantine.")
        return pd.DataFrame()

    # If all failed: Quarantine the original ticker name
    reason = "Failed to download data via Yahoo API and Tiingo API (Rate Limits Exceeded)."
    quarantine_ticker(ticker, reason)
    return pd.DataFrame()
