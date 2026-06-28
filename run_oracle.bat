@echo off
cd /d "C:\Users\AviShemla\AntiGravity"

echo ===================================================
echo Starting The Oracle Web Application (FastAPI)...
echo Listening on http://127.0.0.1:8000
echo ===================================================

start "" /b "C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m uvicorn server:app --host 0.0.0.0 --port 8000
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8000
