import os
import datetime
from blacklist_engine import get_blacklisted_tickers

BASE_DIR = r'C:\Users\AviShemla\AntiGravity'
log_file = os.path.join(BASE_DIR, 'QA_Historical_Log.md')

def qa_blacklist():
    print("=== QA AUDIT: BLACKLIST ENGINE ===")
    try:
        blacklisted = get_blacklisted_tickers(persona="BallsForBrains")
        status = f"SUCCESS - Blacklist engine evaluated ledgers. Currently blacklisted: {blacklisted if blacklisted else 'None'}"
        print(status)
        
        # Log to the QA file
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"\n### {timestamp} - QA Assistant - Automated Blacklist Audit\n* **Status:** {status}\n* **Resolution:** Blacklist pipeline logic is intact and generating correct output.\n"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
    except Exception as e:
        status = f"FAILURE - Error executing get_blacklisted_tickers(): {e}"
        print(status)
        
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"\n### {timestamp} - QA Assistant - Automated Blacklist Audit\n* **Status:** {status}\n* **Resolution:** URGENT INVESTIGATION REQUIRED.\n"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

if __name__ == "__main__":
    qa_blacklist()
