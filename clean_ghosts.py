import psutil
import time

print("Hunting for Ghost Processes...")
now = time.time()
killed = 0

for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
    try:
        cmdline = p.info.get('cmdline')
        if not cmdline: continue
        cmd_str = " ".join(cmdline).lower()
        
        # Protect Watchdog and Uvicorn
        if "master_watchdog" in cmd_str or "uvicorn" in cmd_str:
            continue
            
        # Target Python processes
        if "python" in p.info.get('name', '').lower() or "py.exe" in p.info.get('name', '').lower():
            # If running for more than 3600 seconds (1 hour)
            if now - p.info['create_time'] > 3600:
                print(f"Purging Ghost Process (Running > 1hr): PID {p.info['pid']} -> {cmd_str}")
                p.kill()
                killed += 1
    except Exception:
        pass

print(f"Successfully purged {killed} ghost processes.")
