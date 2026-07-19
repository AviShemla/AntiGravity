import os
import time
import requests
import json
import datetime
import pandas as pd
import numpy as np
import yfinance as yf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

    safe_print(f"  [YFINANCE] Fetching {ticker}...")
    try:
        if start:
            df = yf.Ticker(ticker).history(start=start)
        else:
            rng = period if period else "5y"
            df = yf.Ticker(ticker).history(period=rng)
            
        if not df.empty and 'Close' in df.columns:
            time.sleep(5) # Prevent rate limiting (User requested 5s)
            return df
    except Exception as e:
        safe_print(f"  [YFINANCE ERROR] {e}")

    # Fallback 1: Direct API
    time.sleep(5) # Backoff before hitting direct API
    df = download_ticker_direct_api(ticker, period=period, start=start)
    if not df.empty:
        safe_print(f"  [SUCCESS] Resolved data for {ticker} using direct Yahoo API failover.")
        return df

    # If both failed: Quarantine the ticker
    reason = "Failed to download data via direct API (Market closed, ticker delisted, or Rate Limit Exceeded)."
    quarantine_ticker(ticker, reason)
    return pd.DataFrame()
