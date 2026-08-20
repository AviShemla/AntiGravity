$source = "C:\Users\AviShemla\AntiGravity"
$destinationFolder = "C:\Users\AviShemla\AG_BCK"
$destinationFile = "$destinationFolder\AntiGravity_Full_Migration_Backup.zip"

Write-Host "Creating AG_BCK directory if it doesn't exist..." -ForegroundColor Yellow
if (-not (Test-Path $destinationFolder)) {
    New-Item -ItemType Directory -Force -Path $destinationFolder
}

if (Test-Path $destinationFile) {
    Write-Host "Removing old backup..." -ForegroundColor Yellow
    Remove-Item -Force $destinationFile
}

Write-Host "Compressing the AntiGravity ecosystem into a single package..." -ForegroundColor Yellow
tar -a -c -f $destinationFile --exclude=".pytest_cache" --exclude="__pycache__" --exclude=".git" *

Write-Host "Migration Backup Complete! Package successfully exported to Google Drive: $destinationFile" -ForegroundColor Green
