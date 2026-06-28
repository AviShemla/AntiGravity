@echo off
cd /d "C:\Users\AviShemla\AntiGravity"

echo "Attempting to boot master pipeline with primary Python Engine..." > master_pipeline_log.txt
"C:\Users\AviShemla\AppData\Local\Python\pythoncore-3.14-64\python.exe" -u laptop_catchup_controller.py >> master_pipeline_log.txt 2>&1

IF %ERRORLEVEL% NEQ 0 (
    echo "CRITICAL: Primary Python Engine failed or crashed! Attempting automatic failover to secondary bin\python.exe..." >> master_pipeline_log.txt
    "C:\Users\AviShemla\AppData\Local\Python\bin\python.exe" -u laptop_catchup_controller.py >> master_pipeline_log.txt 2>&1
)
