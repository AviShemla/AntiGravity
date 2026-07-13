import urllib.request
import urllib.error
import json
import time
import datetime
import os

API_BASE = "http://127.0.0.1:80/api"
LOG_FILE = r"C:\Users\AviShemla\AntiGravity\master_watchdog.log"
PERSONAS = ["Conservative", "Neutral", "BallsForBrains"]

INCEPTION_DATES = {
    "BallsForBrains": "2026-06-26",
    "Conservative": "2026-07-08",
    "Dynamic": "2026-07-08",
    "ETF_BallsForBrains": "2026-06-29",
    "ETF_Conservative": "2026-06-22",
    "ETF_Dynamic": "2026-06-25",
    "ETF_Neutral": "2026-06-22",
    "Neutral": "2026-07-08"
}

def log_alert(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] QA_UI_AGENT_ALERT: {msg}"
    print(log_line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_line + "\n")
    except:
        pass
        
    try:
        import subprocess
        script_path = os.path.join(r"C:\Users\AviShemla\AntiGravity", "send_email_notification.py")
        subprocess.Popen([r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe", script_path, "AntiGravity QA Alert - UI Agent", msg], creationflags=0x08000000)
    except Exception as e:
        print(f"Failed to trigger email alert: {e}")

def fetch_json(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
            data = json.loads(response.read().decode())
            return True, data
    except urllib.error.HTTPError as e:
        return False, f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"URL Error: {e.reason}"
    except Exception as e:
        return False, f"Exception: {str(e)}"

def run_qa():
    errors_found = 0
    print("--- Starting Dashboard UI Health QA ---")
    
    # 1. Test Holdings Endpoints (Single & ETF)
    for p in PERSONAS:
        for mode in ["Single", "ETF"]:
            url = f"{API_BASE}/holdings?persona={p}&mode={mode}"
            success, data = fetch_json(url)
            
            if not success:
                log_alert(f"Failed to fetch {mode} Holdings for {p}. Error: {data}")
                errors_found += 1
                continue
                
            try:
                # Mathematically verify payload structure
                if not isinstance(data.get('total_equity'), (int, float)):
                    log_alert(f"Malformed total_equity for {p} ({mode})")
                    errors_found += 1
                if not isinstance(data.get('total_return'), (int, float)):
                    log_alert(f"Malformed total_return for {p} ({mode})")
                    errors_found += 1
                dates_array = data.get('equity_curve', {}).get('dates')
                if not isinstance(dates_array, list) or len(dates_array) == 0:
                    log_alert(f"Malformed equity_curve dates for {p} ({mode})")
                    errors_found += 1
                else:
                    # Verify the data isn't stale (Max 4 days old to account for long weekends)
                    last_date_str = dates_array[-1]
                    last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d")
                    days_old = (datetime.datetime.now() - last_date).days
                    if days_old > 4:
                        log_alert(f"STALE API DATA for {p} ({mode})! Last date is {last_date_str} ({days_old} days old!)")
                        errors_found += 1
                        
                    # Verify history length matches inception date precisely
                    p_name = p if mode == 'Single' else f"ETF_{p}"
                    inception = INCEPTION_DATES.get(p_name)
                    if inception:
                        first_date_str = dates_array[0]
                        # Only alert if the first date in the array is strictly AFTER the inception date.
                        # If the array starts slightly earlier, that's fine.
                        if datetime.datetime.strptime(first_date_str, "%Y-%m-%d") > datetime.datetime.strptime(inception, "%Y-%m-%d"):
                            log_alert(f"MISSING HISTORY for {p_name}! Expected history to start by {inception}, but started on {first_date_str}.")
                            errors_found += 1
            except Exception as e:
                log_alert(f"Validation exception for {p} ({mode}): {str(e)}")
                errors_found += 1

    # 1.5 Test Shadow API Endpoint
    url = f"{API_BASE}/prod_shadow"
    success, data = fetch_json(url)
    if not success:
        log_alert(f"Failed to fetch Prod vs Shadow endpoint. Error: {data}")
        errors_found += 1
    else:
        try:
            dates_array = data.get('dates', [])
            if not isinstance(dates_array, list) or len(dates_array) == 0:
                log_alert("Malformed Prod vs Shadow dates array.")
                errors_found += 1
            else:
                last_date_str = dates_array[-1]
                last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d")
                days_old = (datetime.datetime.now() - last_date).days
                if days_old > 4:
                    log_alert(f"STALE SHADOW API DATA! Last date is {last_date_str} ({days_old} days old!)")
                    errors_found += 1
        except Exception as e:
            log_alert(f"Validation exception for Shadow API: {str(e)}")
            errors_found += 1

    # 2. Test Olympic Tab
    url = f"{API_BASE}/olympic"
    success, data = fetch_json(url)
    if not success:
        log_alert(f"Failed to fetch Olympic endpoint. Error: {data}")
        errors_found += 1
    else:
        try:
            if 'EL_CAP' not in data.get('metrics', {}):
                log_alert(f"Olympic data missing EL_CAP metrics")
                errors_found += 1
            if not isinstance(data.get('chart_data', {}).get('CHAMPION'), list):
                log_alert(f"Olympic data missing CHAMPION chart array")
                errors_found += 1
        except Exception as e:
            log_alert(f"Validation exception for Olympic tab: {str(e)}")
            errors_found += 1
            
    if errors_found == 0:
        print("--- Dashboard UI Health QA Passed (0 Errors) ---")
    else:
        log_alert(f"Dashboard QA completed with {errors_found} critical errors!")

if __name__ == "__main__":
    run_qa()
