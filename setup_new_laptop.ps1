# setup_new_laptop.ps1
# AntiGravity - Automated Laptop Provisioning Script
# This script sets up a new laptop to act as a lightweight client for the Vultr-hosted Master Pipeline.

Write-Host "==============================================="
Write-Host " AntiGravity - New Laptop Provisioning Script"
Write-Host "==============================================="

# 1. Check Python Installation
if (!(Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python is not installed or not in PATH! Please install Python 3.10+ before running this script." -ForegroundColor Red
    exit
}

Write-Host "[+] Python detected." -ForegroundColor Green

# 2. Check Git Installation
if (!(Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Git is not installed! Please install Git for Windows." -ForegroundColor Red
    exit
}

Write-Host "[+] Git detected." -ForegroundColor Green

# 3. Setup Virtual Environment
Write-Host "-> Creating Python Virtual Environment (venv)..."
python -m venv venv
.\venv\Scripts\activate

# 4. Install Dependencies
Write-Host "-> Installing Python Dependencies (Prefect, Turso LibSQL, etc.)..."
pip install --upgrade pip
pip install prefect libsql-client pandas numpy yfinance requests

# 5. Connect Prefect to Remote Orchestrator
Write-Host "-> Configuring Prefect to point to Vultr Cloud Orchestrator..."
prefect config set PREFECT_API_URL="http://66.42.118.26:8655/api"

# 6. Verify Turso .env configuration
if (!(Test-Path ".env")) {
    Write-Host "[WARNING] .env file not found. Creating a placeholder .env file..." -ForegroundColor Yellow
    Set-Content -Path ".env" -Value "TURSO_URL=libsql://antigravity-master-youraccount.turso.io`nTURSO_AUTH_TOKEN=your_token_here"
    Write-Host "Please remember to paste your actual Turso keys into the .env file!" -ForegroundColor Yellow
} else {
    Write-Host "[+] .env file detected." -ForegroundColor Green
}

# 7. Create Vultr Dashboard Shortcut
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$Home\Desktop\AntiGravity Dashboard.url")
$Shortcut.TargetPath = "http://66.42.118.26/index.html"
$Shortcut.Save()

Write-Host "==============================================="
Write-Host " Provisioning Complete!"
Write-Host " A shortcut to the Master Dashboard has been placed on your Desktop."
Write-Host " You are now running on Vultr Cloud Compute."
Write-Host "==============================================="
pause
