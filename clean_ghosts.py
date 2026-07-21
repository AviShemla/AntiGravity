import os
import sys
import time
import psutil
import datetime
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "zombie_hunter.log")

def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {msg}"
    print(log_line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_line + "\n")
    except Exception:
        pass

def hunt_zombies():
    log("=== ZOMBIE HUNTER INITIATED ===")
    now = time.time()
    killed_processes = []
    deleted_files = []
    
    # 1. HUNT GHOST PROCESSES
    for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            cmdline = p.info.get('cmdline')
            if not cmdline: continue
            cmd_str = " ".join(cmdline).lower()
            
            # Protect Uvicorn, and long-running pipelines
            if any(w in cmd_str for w in ["uvicorn", "catchup_controller", "run_backtests"]):
                continue
                
            # Target Python processes
            if "python" in p.info.get('name', '').lower() or "py.exe" in p.info.get('name', '').lower():
                # If running for more than 1200 seconds (20 mins)
                if now - p.info['create_time'] > 1200:
                    msg = f"Purged Ghost Process (Running > 20min): PID {p.info['pid']} -> {cmd_str}"
                    log(msg)
                    killed_processes.append(msg)
                    p.kill()
        except Exception:
            pass
            
    # 2. HUNT DEAD LOCKFILES
    lock_patterns = [".lock", "in_progress.txt", "running.pid"]
    search_dirs = [BASE_DIR, os.path.join(BASE_DIR, "financial_data")]
    
    for d in search_dirs:
        if not os.path.exists(d): continue
        for fname in os.listdir(d):
            # Check if file matches any lock pattern
            if any(pat in fname.lower() for pat in lock_patterns):
                fpath = os.path.join(d, fname)
                try:
                    mtime = os.path.getmtime(fpath)
                    # If lockfile is older than 60 minutes
                    if now - mtime > 3600:
                        msg = f"Destroyed Stale Lockfile: {fpath}"
                        log(msg)
                        deleted_files.append(msg)
                        os.remove(fpath)
                except Exception as e:
                    log(f"Error checking file {fpath}: {e}")
                    
    # 3. NOTIFY ADMIN IF ACTION WAS TAKEN
    if killed_processes or deleted_files:
        log("Taking action! Notifying admin via email...")
        email_subject = "⚠️ ZOMBIE HUNTER TRIGGERED: System Auto-Healed"
        
        email_body = "The Zombie Hunter protocol successfully detected and neutralized the following anomalies to keep the system running:\n\n"
        if killed_processes:
            email_body += "== KILLED PROCESSES ==\n" + "\n".join(killed_processes) + "\n\n"
        if deleted_files:
            email_body += "== DELETED LOCKFILES ==\n" + "\n".join(deleted_files) + "\n\n"
            
        email_body += "The system is running OK as expected. No further manual action is required."
        
        try:
            python_exe = sys.executable
            subprocess.run([python_exe, os.path.join(BASE_DIR, "send_email_notification.py"), email_subject, email_body], cwd=BASE_DIR)
        except Exception as e:
            log(f"Failed to send alert email: {e}")
            
    else:
        log("Scan Complete: System is clean. No zombies found.")
        
if __name__ == "__main__":
    hunt_zombies()
