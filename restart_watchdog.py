import psutil
import subprocess
import os

BASE_DIR = r"C:\Users\AviShemla\AntiGravity"
PYTHON_EXE = r"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe"

for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = p.info.get('cmdline')
        if cmdline:
            cmd_str = " ".join(cmdline).lower()
            if "master_watchdog.py" in cmd_str and "python" in p.info.get('name', '').lower():
                print(f"Killing old watchdog PID: {p.info['pid']}")
                p.terminate()
    except Exception:
        pass

print("Starting new watchdog...")
subprocess.Popen(
    [PYTHON_EXE, "master_watchdog.py"], 
    cwd=BASE_DIR, 
    creationflags=0x08000000,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
print("Restart complete.")
