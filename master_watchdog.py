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
        "cmd": [PYTHON_EXE, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80", "--reload"],
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
        "time": "05:00",
        "cmd": ["git", "add", ".", "&&", "git", "commit", "-m", "Automated Backup", "&&", "git", "push"],
        "last_run": None,
        "shell": True
    },
    "daily_migration_backup": {
        "time": "23:30",
        "cmd": [PYTHON_EXE, os.path.join(BASE_DIR, "execute_daily_migration.py")],
        "last_run": None
    },
    "weekend_trainer_stock": {
        "time": "14:00",
        "day_of_week": 5,  # 5 = Saturday
        "cmd": [PYTHON_EXE, os.path.join(BASE_DIR, "weekend_dl_trainer.py")],
        "last_run": None
    },
    "weekend_trainer_etf": {
        "time": "16:00",
        "day_of_week": 5,  # 5 = Saturday
        "cmd": [PYTHON_EXE, os.path.join(BASE_DIR, "etf_weekend_dl_trainer.py")],
        "last_run": None
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

def prune_ghost_processes(max_ttl_seconds=3600):
    current_time = time.time()
    whitelist = ['uvicorn', 'intraday_tracker.py', 'vix_monitor.py', 'master_watchdog.py', 'weekend_dl_trainer.py', 'etf_weekend_dl_trainer.py', 'run_backtests.py', 'backtest_worker.py']
    
    for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            name = p.info.get('name', '')
            if name and 'python' in name.lower():
                cmdline = p.info.get('cmdline')
                if not cmdline:
                    continue
                cmd_str = " ".join(cmdline).lower()
                
                is_whitelisted = any(w.lower() in cmd_str for w in whitelist)
                if not is_whitelisted:
                    age_seconds = current_time - p.info['create_time']
                    if age_seconds > max_ttl_seconds:
                        log(f"GHOST PRUNER: Detected zombie python process PID {p.info['pid']} running for {age_seconds/60:.1f} minutes. Terminating.")
                        p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

def check_single_instance():
    current_pid = os.getpid()
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        if p.info['pid'] == current_pid:
            continue
        try:
            cmdline = p.info.get('cmdline')
            if not cmdline:
                continue
            cmd_str = " ".join(cmdline).lower()
            if "master_watchdog.py" in cmd_str and "python" in cmd_str:
                log(f"CRITICAL: Another instance of master_watchdog (PID {p.info['pid']}) is already running. Exiting to prevent collisions.")
                # sys.exit(0)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
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
            # CREATE_NO_WINDOW = 0x08000000 ensures it runs truly silently in the background
            subprocess.Popen(
                config['cmd'], 
                cwd=config['cwd'], 
                creationflags=0x08000000,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

def check_schedule():
    now = datetime.datetime.now()
    current_time_str = now.strftime("%H:%M")
    current_date = now.date()

    for task_name, config in SCHEDULED_TASKS.items():
        # Check day of week if specified (0 = Monday, 6 = Sunday)
        if 'day_of_week' in config and now.weekday() != config['day_of_week']:
            continue
            
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
    check_single_instance()
    log("Master Watchdog Initialized. Supervising the AntiGravity ecosystem...")
    loop_count = 0
    while True:
        try:
            check_and_revive_daemons()
            check_schedule()
            prune_ghost_processes(7200)
            
            # Run UI QA Agent every 15 minutes (15 loops of 60s)
            if loop_count % 15 == 0:
                subprocess.Popen([PYTHON_EXE, os.path.join(BASE_DIR, "qa_api_health.py")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
            # Run Task Auditor Agent every 60 minutes (60 loops of 60s)
            if loop_count % 60 == 0:
                subprocess.Popen([PYTHON_EXE, os.path.join(BASE_DIR, "qa_task_auditor.py")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
        except Exception as e:
            log(f"CRITICAL WATCHDOG ERROR: {e}")
        
        loop_count += 1
        # Sleep for 60 seconds
        time.sleep(60)
