import os
import sys
import time
import subprocess
import datetime
import psutil

# Configuration
BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
PYTHON_EXE = r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe"

DAEMONS = {
    "web_server": {
        "match": "uvicorn",
        "cmd": [PYTHON_EXE, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80"],
        "cwd": BASE_DIR
    },
    "intraday_sniper": {
        "match": "intraday_tracker.py",
        "cmd": [PYTHON_EXE, os.path.join(BASE_DIR, "intraday_tracker.py")],
        "cwd": BASE_DIR
    },
    "vix_watchdog": {
        "match": "vix_monitor.py",
        "cmd": [PYTHON_EXE, os.path.join(BASE_DIR, "vix_monitor.py")],
        "cwd": BASE_DIR
    }
}

SCHEDULED_TASKS = {
    "daily_pipeline": {
        "time": "01:00",
        "cmd": [PYTHON_EXE, os.path.join(BASE_DIR, "master_pipeline.py")],
        "last_run": None
    },
    "git_backup": {
        "time": "02:00",
        "cmd": ["git", "add", ".", "&&", "git", "commit", "-m", "Automated Backup", "&&", "git", "push"],
        "last_run": None,
        "shell": True
    }
}

def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    print(log_line)
    try:
        with open(os.path.join(BASE_DIR, "master_watchdog.log"), "a") as f:
            f.write(log_line + "\n")
    except Exception:
        pass

def check_and_revive_daemons():
    running_matches = set()
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = p.info.get('cmdline')
            if not cmdline:
                continue
            cmd_str = " ".join(cmdline).lower()
            for name, config in DAEMONS.items():
                if config['match'].lower() in cmd_str:
                    running_matches.add(name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    for name, config in DAEMONS.items():
        if name not in running_matches:
            log(f"ALERT: {name} is NOT running. Reviving it silently in the background...")
            # CREATE_NEW_CONSOLE = 0x00000010 ensures it runs in a visible CMD window
            subprocess.Popen(
                config['cmd'], 
                cwd=config['cwd'], 
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )

def check_schedule():
    now = datetime.datetime.now()
    current_time_str = now.strftime("%H:%M")
    current_date = now.date()

    for task_name, config in SCHEDULED_TASKS.items():
        # If the current time matches the target time (down to the minute)
        if current_time_str == config['time']:
            # Make sure we haven't already run it today
            if config['last_run'] != current_date:
                log(f"CRON: Executing scheduled task '{task_name}' at {current_time_str}...")
                try:
                    if config.get('shell', False):
                        subprocess.Popen(" ".join(config['cmd']), cwd=BASE_DIR, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    else:
                        subprocess.Popen(config['cmd'], cwd=BASE_DIR, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    config['last_run'] = current_date
                except Exception as e:
                    log(f"ERROR: Failed to run scheduled task {task_name}: {e}")

if __name__ == "__main__":
    log("Master Watchdog Initialized. Supervising the AntiGravity ecosystem...")
    while True:
        try:
            check_and_revive_daemons()
            check_schedule()
        except Exception as e:
            log(f"CRITICAL WATCHDOG ERROR: {e}")
        
        # Sleep for 60 seconds
        time.sleep(60)
