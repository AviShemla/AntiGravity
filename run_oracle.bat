@echo off
cd /d "C:\Users\AviShemla\AntiGravity"

echo ===================================================
echo Ensuring old Oracle background processes are stopped...
echo ===================================================
powershell -Command "Stop-Process -Name 'python', 'pythonw' -Force -ErrorAction SilentlyContinue"

echo ===================================================
echo Starting The Oracle Web Application (FastAPI)...
echo Listening on port 80 (http://localhost)
echo ===================================================

:: Use pythonw.exe to run without a console window, which prevents stdout pipe blocking/hanging!
start "" "C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" -m uvicorn server:app --host 0.0.0.0 --port 80

echo ===================================================
echo Starting The Master Watchdog (Background Supervisor)...
echo ===================================================
start "" "C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" master_watchdog.py

ping 127.0.0.1 -n 3 > nul
start "" http://127.0.0.1/
