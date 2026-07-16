@echo off
color 0A
echo ===================================================
echo   AntiGravity - New Laptop Plug & Play Setup
echo ===================================================
echo.
echo Installing Required Python Libraries...
py -m pip install --upgrade pip
py -m pip install -r requirements.txt

echo.
echo Launching the AntiGravity Master Watchdog...
start /min py master_watchdog.py

echo.
echo Launching the Uvicorn Dashboard Server...
start py start_server.py

echo.
echo Setup Complete! 
echo The Watchdog is now running in the background.
echo The Premium UI is accessible at http://127.0.0.1
pause
