import psutil

print("Hunting for deadlocked Uvicorn and Zombie scripts...")
killed = 0
for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = p.info.get('cmdline')
        if not cmdline: continue
        cmd_str = " ".join(cmdline).lower()
        
        # We want to kill uvicorn (which is deadlocked) and any tracker scripts
        if "uvicorn" in cmd_str or "prod_vs_shadow_tracker" in cmd_str:
            print(f"Killing Zombie/Deadlocked Process: PID {p.info['pid']} -> {cmd_str}")
            p.kill()
            killed += 1
    except Exception as e:
        pass

print(f"Successfully destroyed {killed} deadlocked processes.")
