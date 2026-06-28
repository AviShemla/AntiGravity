@echo off
TITLE AntiGravity Intraday Sniper
color 0A
echo =======================================================
echo     AntiGravity Intraday Execution Engine Activated
echo =======================================================
echo.
echo Launching the Intraday Tracker...
echo Leave this window open. It will automatically sleep 
echo during closed market hours and wake up at the opening bell.
echo Starting VIX Watchdog Engine in the background...
start "VIX Watchdog" "C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe" "C:\Users\AviShemla\AntiGravity\vix_monitor.py"

echo.
"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe" "C:\Users\AviShemla\AntiGravity\intraday_tracker.py"
pause
