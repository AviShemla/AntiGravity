import psutil
killed = 0
for p in psutil.process_iter(['cmdline', 'pid']):
    try:
        cmdline = p.info.get('cmdline')
        if not cmdline: continue
        cmd_str = " ".join(cmdline)
        if any(x in cmd_str for x in ['SPY.py', 'intraday_tracker.py', 'vix_monitor.py']):
            print(f"Killing: {cmd_str}")
            p.kill()
            killed += 1
    except Exception:
        pass
print(f"Killed {killed} rogue scripts.")
