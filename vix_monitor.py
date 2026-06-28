import yfinance as yf
import time
import json
import os
import datetime

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
OUTPUT_FILE = os.path.join(BASE_DIR, "financial_data", "vix_score.json")

def fetch_vix():
    try:
        df = yf.download("^VIX", period="1d", interval="1m", progress=False)
        if df.empty: return None
        if isinstance(df.columns, type(df.index)): # handle multiindex if present
            pass
        latest_vix = float(df['Close'].iloc[-1].item())
        return latest_vix
    except Exception as e:
        print(f"Failed to fetch VIX: {e}")
        return None

import pandas_market_calendars as mcal
import pytz

def main():
    print("=========================================")
    print(" VIX WATCHDOG ENGINE INITIATED")
    print("=========================================")
    
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    ny_tz = pytz.timezone('America/New_York')
    
    while True:
        now_ny = datetime.datetime.now(ny_tz)
        nyse = mcal.get_calendar('NYSE')
        valid_today = nyse.valid_days(start_date=now_ny.date(), end_date=now_ny.date())
        is_market_day = len(valid_today) > 0
        market_open = now_ny.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_ny.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if is_market_day and (market_open <= now_ny < market_close):
            vix_val = fetch_vix()
            if vix_val is not None:
                data = {
                    "vix_value": round(vix_val, 2),
                    "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(OUTPUT_FILE, 'w') as f:
                    json.dump(data, f)
                print(f"[{data['last_updated']}] Live VIX Score Updated: {vix_val:.2f}")
            
            # Sleep for 5 minutes (300 seconds) before checking again
            time.sleep(300)
        else:
            print(f"[{now_ny.strftime('%Y-%m-%d %H:%M:%S EST')}] Market is CLOSED. Zzz for 15 minutes...")
            time.sleep(900)

if __name__ == "__main__":
    main()
